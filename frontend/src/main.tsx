import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { PendingList } from "./screens/PendingList";
import { RunDetailPage } from "./screens/RunDetail";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<PendingList />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
