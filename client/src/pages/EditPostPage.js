import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import axios from 'axios';
import Editor from "../Editor";

export default function EditPostPage() {
    const {id} = useParams();
    const [title, setTitle] = useState("");
    const [cover_image, setCoverImage] = useState("");
    const [content, setContent] = useState("");

    const navigate = useNavigate();

    useEffect(() => {
        axios.get(`http://localhost:8000/post/${id}`)
            .then(response => {
                console.log(response.data.message)
                console.log(response.data.post)
                setTitle(response.data.post.title);
                setContent(response.data.post.content);
                setCoverImage(response.data.post.cover_image);
            })
            .catch(error => {
                console.error("There was an error fetching the post!", error)
            });
    }, [id]);

    async function updatePost(ev) {
        ev.preventDefault();

        console.log(id);

        const postData = new FormData();
        postData.append("post_id", id);
        postData.append("title", title);
        postData.append("content", content);
        if (cover_image instanceof File) {
            postData.append("cover_image", cover_image);
        }

        try {
            console.log(postData);
            const response = await axios.put("http://localhost:8000/edit",
                postData,
                { headers: {
                        "Content-Type": "multipart/form-data"
                }
            });

            console.log(response.data);
            setCoverImage(cover_image + `?t=${new Date().getTime()}`);
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
        <form onSubmit={updatePost}>
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
            <button style={{marginTop:"5px"}}>Edit Post</button>
        </form>
)

}

