import "./App.css";
import Layout from "./Layout";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import CreatePostPage from "./pages/CreatePostPage";
import { UserProvider } from "./context/UserContext";
import PostPage from "./pages/PostPage";
import {Route, Routes} from "react-router-dom";


function App() {
  return (
    <UserProvider>
      <Routes>
        <Route path="/" element={<Layout/>}>
          <Route index element={<HomePage/>} />
          <Route path="/login" element = {<LoginPage/>} />
          <Route path="/register" element = {<RegisterPage/>} />
          <Route path="/create" element = {<CreatePostPage/>} />
          <Route path="/post/:id" element = {<PostPage/>} />
        </Route>
      </Routes>
    </UserProvider>
  );
}

export default App;
