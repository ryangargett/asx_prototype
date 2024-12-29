import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Editor from "../Editor";
import "react-quill-new/dist/quill.snow.css";
import axios from 'axios';

export default function CreatePostPage() {
    const [title, setTitle] = useState("");
    const [cover_image, setCoverImage] = useState("");
    const [content, setContent] = useState("");

    const navigate = useNavigate();

    //TODO: add sub-text image upload

    const postData = new FormData();
    postData.append("title", title);
    postData.append("cover_image", cover_image);
    postData.append("content", content);

    async function createPost(ev) {
        ev.preventDefault();

        try {
            console.log(cover_image);
            const response = await axios.post("http://localhost:8000/create",
                postData,
                { headers: {
                        "Content-Type": "multipart/form-data"
                }
            });

            console.log(response.data.message);
        } catch (error) {
            if (error.response && error.response.data && error.response.data.detail) {
                alert(error.response.data.detail);
            } else {
                alert("An unexpected error occurred please try again later");
            }
        }
        navigate("/");
    }

    return (
        <form onSubmit={createPost}>
            <input 
                type="title" 
                placeholder={"Title"} 
                value={title} 
                onChange={ev => setTitle(ev.target.value)} 
            />
            <input 
                type="file"
                onChange={ev => setCoverImage(ev.target.files[0])}
            />
            <Editor 
                onChange={setContent} value={content}>
            </Editor>
            <button style={{marginTop:"5px"}}>Create Post</button>
        </form>
)

}

