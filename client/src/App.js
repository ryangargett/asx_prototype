import "./App.css";
import Layout from "./Layout";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import CreatePostPage from "./pages/CreatePostPage";
import { UserProvider } from "./context/UserContext";
import { PostProvider } from "./context/PostContext";
import PostPage from "./pages/PostPage";
import EditPostPage from "./pages/EditPostPage";
import {Route, Routes} from "react-router-dom";


function App() {
  return (
    <UserProvider>
      <PostProvider>
        <Routes>
          <Route path="/" element={<Layout/>}>
            <Route index element={<HomePage/>} />
            <Route path="/login" element = {<LoginPage/>} />
            <Route path="/register" element = {<RegisterPage/>} />
            <Route path="/create" element = {<CreatePostPage/>} />
            <Route path="/post/:id" element = {<PostPage/>} />
            <Route path="/edit/:id" element = {<EditPostPage/>} />
          </Route>
        </Routes>
      </PostProvider>
    </UserProvider>
  );
}

export default App;
