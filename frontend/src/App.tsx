import { Navigate, Route, Routes } from "react-router-dom";

import { SkipLink, Spinner } from "./components/ui";
import { AdminPage } from "./pages/AdminPage";
import { ChatPage } from "./pages/ChatPage";
import { LoginPage } from "./pages/LoginPage";
import { useSession } from "./state/session";

export default function App() {
  const { status, session } = useSession();

  if (status === "loading") {
    return (
      <div className="h-full flex items-center justify-center">
        <SkipLink />
        <Spinner label="Loading console…" />
      </div>
    );
  }

  if (status === "signed-out" || !session) {
    return <LoginPage />;
  }

  return (
    <Routes>
      <Route path="/" element={<ChatPage />} />
      {/* Conversation id in the path, so resuming a thread is a shareable URL. */}
      <Route path="/c/:conversationId" element={<ChatPage />} />
      <Route
        path="/admin"
        element={session.user.role === "admin" ? <AdminPage /> : <Navigate to="/" replace />}
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
