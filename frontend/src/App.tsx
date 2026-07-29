import { Route, Routes } from "react-router-dom";
import "./App.css";
import ResultsPage from "./pages/ResultsPage";
import UploadPage from "./pages/UploadPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<UploadPage />} />
      <Route path="/job/:jobId" element={<ResultsPage />} />
    </Routes>
  );
}
