import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import AdminHome from './pages/AdminHome';
import Editor from './pages/Editor';

export default function App() {
  // Express serves this SPA at /admin (vite base="/admin/") so the router
  // basename mirrors that. Public routes like /regulations/* are still
  // served as static files by Express and never hit React.
  return (
    <BrowserRouter basename="/admin">
      <Routes>
        <Route path="/" element={<AdminHome />} />
        <Route path="/new" element={<Editor mode="create" />} />
        <Route path="/edit/:slug" element={<Editor mode="edit" />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
