import { Route, Routes } from 'react-router-dom'
import Shell from './components/Shell.jsx'
import ChatPage from './pages/ChatPage.jsx'
import NotFoundPage from './pages/NotFoundPage.jsx'
import ReviewDetailPage from './pages/ReviewDetailPage.jsx'
import SettingsPage from './pages/SettingsPage.jsx'

/**
 * Three surfaces, one workspace:
 *   /                 the composer + conversation (start a review or ask)
 *   /reviews/:id      one review in depth (findings list / diff)
 *   /settings         keys, models, comment behaviour
 */
export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<ChatPage />} />
        <Route path="/reviews/:reviewId" element={<ReviewDetailPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
