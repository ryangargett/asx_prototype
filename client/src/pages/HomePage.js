import { useEffect, useState } from "react";
import Post from "../Post";
import axios from "axios";

export default function HomePage() {
    
    const [posts, setPosts] = useState([]);
    
    useEffect(() => {
        axios.get("http://localhost:8000/posts")
            .then(response => {
                console.log(response.data.posts);
                setPosts(response.data.posts);
                console.log(response.data.message);
            })
            .catch(error => {
                console.error("There was an error fetching the posts!", error);
            });
    }, []);
    return (
        <>
            {posts.length > 0 && posts.map(post => (
                <Post key = {post.post_id} {...post} />
            ))}
        </>
    )
}