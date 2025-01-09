import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import Editor from "../Editor";
import "react-quill-new/dist/quill.snow.css";
import axios from 'axios';

export default function CreatePostPage() {
    const [title, setTitle] = useState("");
    const [cover_image, setCoverImage] = useState(null);
    const [coverImageUrl, setCoverImageUrl] = useState("");
    const [content, setContent] = useState("");
    const [pdf, setPdf] = useState(null);
    const [postID, setPostID] = useState(null);
    const [dragging, setDragging] = useState(false);
    const coverImageInputRef = useRef(null);

    const navigate = useNavigate();

    async function createPost(ev) {
        ev.preventDefault();

        const postData = new FormData();
        postData.append("title", title);
        if (cover_image) {
            postData.append("cover_image", cover_image);
        }
        postData.append("content", content);
        if (postID) {
            postData.append("post_id", postID);
        }

        console.log(postData);

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

    const handleDragOver = (ev) => {
        ev.preventDefault();
        setDragging(true);
    };

    const handleDragLeave = () => {
        setDragging(false);
    };

    const handleDrop = async (ev) => {
        ev.preventDefault();
        setDragging(false);
        const file = ev.dataTransfer.files[0];
        if (file && file.type === "application/pdf") {
            setPdf(file);
            const formData = new FormData();
            formData.append("pdf", file);
            try {
                const response = await axios.post("http://localhost:8000/autofill", formData, {
                    headers: {
                        "Content-Type": "multipart/form-data"
                    }
                });
                setTitle(response.data.title);
                setContent(response.data.content);
                setCoverImageUrl(response.data.cover_image);
                setPostID(response.data.post_id);
            } catch (error) {
                alert("An unexpected error occurred when attempting autofill, please try again later: " + error);
            }
        } else {
            alert("Please upload a valid PDF file.");
        }
    };

    return (
        <div className="create-post">
            <form onSubmit={createPost}>
                <h1>Autofill from PDF</h1>
                <div 
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    style={{
                        border: dragging ? "2px dashed #000" : "2px solid #ccc",
                        padding: "20px",
                        marginTop: "10px",
                        textAlign: "center"
                    }}
                >
                    {pdf ? pdf.name : "Drag and drop a PDF file here or click to upload"}
                </div>
                <div>
                    <h1>OR</h1>
                    <h1>Create manually</h1>
                </div>
                <input 
                    type="text" 
                    placeholder={"Title"} 
                    value={title} 
                    onChange={ev => setTitle(ev.target.value)} 
                />
                <input 
                    type="file"
                    ref={coverImageInputRef}
                    onChange={ev => {
                        setCoverImage(ev.target.files[0]);
                        setCoverImageUrl(URL.createObjectURL(ev.target.files[0]));
                    }}
                />
                {coverImageUrl && (
                    <div>
                        <img src={coverImageUrl} alt="Cover" style={{ width: "100px", height: "100px" }} />
                    </div>
                )}
                <div className="article-content">
                    <Editor 
                        onChange={setContent} value={content}>
                    </Editor>
                </div>
                <button style={{marginTop:"5px"}}>Create Post</button>
            </form>
        </div>
    )
}