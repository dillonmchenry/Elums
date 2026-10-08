import { Route, Routes } from "react-router-dom";
import "./apiClient";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { PerformancePage } from "./pages/PerformancePage";
import { ProgressPage } from "./pages/ProgressPage";
import { SingPage } from "./pages/SingPage";
import { SongPage } from "./pages/SongPage";

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/diagnostics" element={<DiagnosticsPage />} />
      {/* Tue Oct 6 (T4): the karaoke playback page — M1's "playable chart". */}
      <Route path="/songs/:id" element={<SongPage />} />
      {/* Wed Oct 7 (W2/W6): capture a take, optionally joining a seed
          via ?join=<performance_id>. */}
      <Route path="/songs/:id/sing" element={<SingPage />} />
      {/* Wed Oct 7 (W5/W6): one take's score + per-note coloring. */}
      <Route path="/performances/:id" element={<PerformancePage />} />
      {/* F8 (Session C, IMPLEMENTATION_PLAN_2026-10-09.md): gated
          progress tracking for one user's own takes of one song. */}
      <Route path="/songs/:id/progress" element={<ProgressPage />} />
    </Routes>
  );
}

export default App;
