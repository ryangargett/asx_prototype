import { useState } from 'react';
import ReactQuill from 'react-quill-new';
import "react-quill-new/dist/quill.snow.css";
import axios from 'axios';

const modules = {
    toolbar: [
      [{ 'header': [1, 2, false] }],
      ['bold', 'italic', 'underline','strike', 'blockquote'],
      [{'list': 'ordered'}, {'list': 'bullet'}, {'indent': '-1'}, {'indent': '+1'}],
      ['link', 'image'],
      ['clean']
    ],
};

const formats = [
    'header',
    'bold', 'italic', 'underline', 'strike', 'blockquote',
    'list', 'indent',
    'link', 'image'
];

export default function CreatePostPage() {

    const [title, setTitle] = useState("");
    const [cover_image, setCoverImage] = useState("");
    const [content, setContent] = useState("");

    //TODO: add sub-text image upload

    const postData = new FormData();
    postData.set("title", title);
    postData.set("cover_image", cover_image[0]); // handle multiple uploads
    postData.set("content", content);

    async function createPost(ev) {
        ev.preventDefault();

        console.log(cover_image);

        //const response = await axios.post("http://localhost:8000/create", {
        //    title,
        //    cover_image,
        //    content
        //});


        //console.log(title, cover_image, content);
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
                onChange={ev => setCoverImage(ev.target.files)}
            />
            <ReactQuill 
                value={content}
                onChange={newValue => setContent(newValue)}
                modules={modules} 
                formats={formats}
            />
            <button style={{marginTop:"5px"}}>Create Post</button>
        </form>
)

}

