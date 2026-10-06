import { Route, Routes } from "react-router-dom";
import "./apiClient";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { SongPage } from "./pages/SongPage";

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/diagnostics" element={<DiagnosticsPage />} />
      {/* Tue Oct 6 (T4): the karaoke playback page — M1's "playable chart". */}
      <Route path="/songs/:id" element={<SongPage />} />
    </Routes>
  );
}

export default App;
