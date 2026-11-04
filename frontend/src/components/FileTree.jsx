import { useState } from 'react'
import { IconFile, IconFolder } from './icons.jsx'

/**
 * Build a nested tree from flat paths:
 *   ["app/api/cart.py", "app/main.py"]
 *   -> app/ { api/ { cart.py }, main.py }
 */
function buildTree(files) {
  const root = { name: '', path: '', children: [], file: null }

  for (const file of files) {
    const parts = file.path.split('/')
    let node = root

    parts.forEach((part, index) => {
      const isLast = index === parts.length - 1
      const path = parts.slice(0, index + 1).join('/')
      let child = node.children.find((candidate) => candidate.name === part)

      if (!child) {
        child = { name: part, path, children: [], file: null }
        node.children.push(child)
      }
      if (isLast) child.file = file
      node = child
    })
  }

  const sort = (node) => {
    node.children.sort((a, b) => {
      const aIsFile = Boolean(a.file)
      const bIsFile = Boolean(b.file)
      if (aIsFile !== bIsFile) return aIsFile ? 1 : -1
      return a.name.localeCompare(b.name)
    })
    node.children.forEach(sort)
  }
  sort(root)

  return root
}

const STATUS_LETTER = {
  added: { char: 'A', className: 'text-ok' },
  modified: { char: 'M', className: 'text-warn' },
  removed: { char: 'D', className: 'text-danger' },
  renamed: { char: 'R', className: 'text-accent' },
}

function FileRow({ file, depth, selected, onSelect, findingCount }) {
  const status = STATUS_LETTER[file.status] || STATUS_LETTER.modified
  const active = selected === file.path

  return (
    <button
      type="button"
      onClick={() => onSelect(file.path)}
      title={file.path}
      style={{ paddingLeft: `${depth * 14 + 8}px` }}
      className={[
        'flex w-full items-center gap-2 rounded-lg py-2 pr-2 text-left text-[13.5px] transition',
        active
          ? 'bg-panel2 text-ink'
          : 'text-muted hover:bg-soft hover:text-ink',
      ].join(' ')}
    >
      <IconFile className="h-3.5 w-3.5 shrink-0 text-muted/70" />
      <span className="truncate font-medium">{file.name}</span>
      <span className={`ml-auto shrink-0 font-mono text-[11.5px] font-bold ${status.className}`}>
        {status.char}
      </span>
      {findingCount > 0 && (
        <span className="shrink-0 rounded-full bg-danger/10 px-1.5 text-[11px] font-semibold text-danger  ">
          {findingCount}
        </span>
      )}
    </button>
  )
}

function TreeNode({ node, depth, selected, onSelect, findingsByFile }) {
  const [open, setOpen] = useState(true)

  if (node.file) {
    return (
      <FileRow
        file={node.file}
        depth={depth}
        selected={selected}
        onSelect={onSelect}
        findingCount={findingsByFile.get(node.file.path)?.length || 0}
      />
    )
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        style={{ paddingLeft: `${depth * 14 + 8}px` }}
        className="flex w-full items-center gap-1.5 rounded-lg py-1.5 pr-2 text-left text-[12px] font-semibold uppercase tracking-wide text-muted hover:bg-soft"
      >
        <span
          className={`inline-block transition-transform ${open ? 'rotate-90' : ''}`}
          aria-hidden="true"
        >
          ›
        </span>
        <IconFolder className="h-3.5 w-3.5" />
        <span className="truncate">{node.name}</span>
      </button>
      {open && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              selected={selected}
              onSelect={onSelect}
              findingsByFile={findingsByFile}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default function FileTree({ files, selected, onSelect, findingsByFile }) {
  const tree = buildTree(files)

  return (
    <div className="space-y-0.5">
      {tree.children.map((node) => (
        <TreeNode
          key={node.path}
          node={node}
          depth={0}
          selected={selected}
          onSelect={onSelect}
          findingsByFile={findingsByFile}
        />
      ))}
    </div>
  )
}
