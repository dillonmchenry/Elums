import { Route, Routes } from "react-router-dom";
import "./apiClient";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import { HomePage } from "./pages/HomePage";

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/diagnostics" element={<DiagnosticsPage />} />
    </Routes>
  );
}

export default App;
