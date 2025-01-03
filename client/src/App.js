import "./App.css";
import Layout from "./Layout";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import {Route, Routes} from "react-router-dom";


function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout/>}>
        <Route index element={<HomePage/>} />
        <Route path="/login" element = {<LoginPage/>} />
        <Route path="/register" element = {<RegisterPage/>} />
      </Route>
    </Routes>
  );
}

export default App;
