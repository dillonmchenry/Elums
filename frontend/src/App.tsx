import { Route, Routes } from "react-router-dom";
import "./apiClient";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/diagnostics" element={<DiagnosticsPage />} />
    </Routes>
  );
}

export default App;
