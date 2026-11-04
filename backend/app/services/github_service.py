"""GitHub API access (PyGithub wrapper).

Keeping every PyGithub call in one file means:
  * the Celery task reads like a story (`fetch → analyse → persist → comment`)
  * network errors become one exception type we can catch and log
  * swapping PyGithub for raw `httpx` later touches exactly one module
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class GitHubError(RuntimeError):
    """Any failure talking to GitHub, with a message safe to store in the DB."""


@dataclass(slots=True)
class ChangedFile:
    """A file in the PR, reduced to what the review engine needs."""

    path: str
    status: str  # added | modified | removed | renamed
    patch: str | None
    additions: int = 0
    deletions: int = 0
    previous_path: str | None = None


@dataclass(slots=True)
class PullRequestInfo:
    """Snapshot of the PR metadata we persist on Review."""

    repo_name: str
    number: int
    title: str
    url: str
    author: str | None
    head_sha: str
    state: str
    files: list[ChangedFile]
    total_additions: int = 0
    total_deletions: int = 0


class GitHubClient:
    """Small, purpose-built GitHub client.

    A token is optional: public repositories can be read anonymously (GitHub
    allows 60 requests/hour per IP). A token unlocks private repos, comment
    posting, and 5,000 requests/hour.
    """

    def __init__(self, token: str = "", api_url: str | None = None) -> None:
        try:
            from github import Github
        except ImportError as exc:  # pragma: no cover - dependency in requirements
            raise GitHubError("the `PyGithub` package is not installed") from exc

        self.authenticated = bool(token)
        self._github = Github(
            # PyGithub reads an empty string as "invalid token", so pass None.
            login_or_token=token or None,
            base_url=(api_url or settings.github_api_url).rstrip("/"),
            timeout=30,
            # Retry idempotent GETs a couple of times on transient 5xx errors.
            retry=2,
        )

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get_pull_request(self, repo_full_name: str, pr_number: int):
        try:
            repo = self._github.get_repo(repo_full_name)
            return repo.get_pull(pr_number)
        except Exception as exc:  # noqa: BLE001 - PyGithub raises many types
            raise GitHubError(f"could not load {repo_full_name}#{pr_number}: {exc}") from exc

    def collect_pr(self, repo_full_name: str, pr_number: int) -> PullRequestInfo:
        """Fetch PR metadata + changed files in one pass."""
        pr = self.get_pull_request(repo_full_name, pr_number)
        try:
            files: list[ChangedFile] = []
            total_additions = total_deletions = 0
            # `get_files()` is a PaginatedList: iterating fetches every page
            # (max 3000 files by GitHub's own limit).
            for f in pr.get_files():
                if len(files) >= 3000:
                    logger.warning("PR %s#%s has more than 3000 files; truncating", repo_full_name, pr_number)
                    break
                total_additions += int(f.additions or 0)
                total_deletions += int(f.deletions or 0)
                files.append(
                    ChangedFile(
                        path=f.filename,
                        status=f.status,
                        patch=getattr(f, "patch", None),
                        additions=int(f.additions or 0),
                        deletions=int(f.deletions or 0),
                        previous_path=getattr(f, "previous_filename", None),
                    )
                )
            return PullRequestInfo(
                repo_name=repo_full_name,
                number=pr.number,
                title=pr.title or "",
                url=pr.html_url or "",
                author=(pr.user.login if pr.user else None),
                head_sha=pr.head.sha,
                state=pr.state,
                files=files,
                total_additions=total_additions,
                total_deletions=total_deletions,
            )
        except GitHubError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GitHubError(f"could not read files for {repo_full_name}#{pr_number}: {exc}") from exc

    def get_file_content(self, repo_full_name: str, path: str, ref: str) -> str | None:
        """Return file text at a commit, or None if it is binary/missing.

        GIT CONCEPT: `ref` is "which version of the file". Here it is the PR's
        head commit SHA, so pyflakes analyses the code *as it would be merged*,
        not whatever happens to be on the default branch.
        """
        try:
            repo = self._github.get_repo(repo_full_name)
            content_file = repo.get_contents(path, ref=ref)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch %s at %s: %s", path, ref[:8], exc)
            return None

        # get_contents can return a list for directories; we only want files.
        if isinstance(content_file, list):
            return None
        try:
            if content_file.encoding == "base64" and content_file.content:
                import base64

                raw = base64.b64decode(content_file.content)
                # Binary sniffing: NUL bytes are a reliable tell.
                if b"\x00" in raw[:8000]:
                    return None
                return raw.decode("utf-8", errors="replace")
            if content_file.decoded_content:
                return content_file.decoded_content.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not decode %s: %s", path, exc)
        return None

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def post_review(
        self,
        repo_full_name: str,
        pr_number: int,
        *,
        body: str,
        comments: list[dict[str, object]],
        commit_sha: str,
    ) -> str | None:
        """Create one PR review with inline comments.

        GIT CONCEPT: a "review" is GitHub's formal object for "I looked at this
        PR". It can be APPROVE / REQUEST_CHANGES / COMMENT. We use COMMENT so
        the bot never blocks merging (a hackathon demo should not gate a merge).

        `comments` use the modern `line` + `side="RIGHT"` anchors, i.e. line
        numbers in the NEW file. GitHub returns 422 if a line is not part of
        the diff, so the caller pre-filters. If posting still fails, we fall
        back to a single summary comment rather than losing the review.
        """
        pr = self.get_pull_request(repo_full_name, pr_number)

        # A review with no inline comments is just a normal PR comment.
        if not comments:
            return self.post_issue_comment(repo_full_name, pr_number, body)

        # GitHub's review API accepts a limited number of comments per request;
        # chunking keeps us well clear of the limit. The summary body goes on
        # the first chunk only, so the PR gets one review per chunk, not spam.
        review_url: str | None = None
        for start in range(0, len(comments), 25):
            chunk = comments[start : start + 25]
            try:
                review = pr.create_review(
                    commit=commit_sha,
                    body=body if start == 0 else "",
                    event="COMMENT",
                    comments=chunk,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Inline review failed (%s); falling back to a summary comment", exc
                )
                try:
                    issue_comment = pr.create_issue_comment(body=body)
                    return issue_comment.html_url
                except Exception as inner:  # noqa: BLE001
                    raise GitHubError(f"could not post review comments: {inner}") from inner

            if review_url is None:
                review_url = review.html_url

        return review_url

    def post_issue_comment(self, repo_full_name: str, pr_number: int, body: str) -> str | None:
        """Plain conversation comment (used for the summary fallback)."""
        pr = self.get_pull_request(repo_full_name, pr_number)
        try:
            comment = pr.create_issue_comment(body=body)
            return comment.html_url
        except Exception as exc:  # noqa: BLE001
            raise GitHubError(f"could not post a comment: {exc}") from exc
