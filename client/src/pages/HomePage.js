import { useEffect } from "react";
import Post from "../Post";
import { usePost } from "../context/PostContext";
import axios from "axios";

export default function HomePage() {
    const { posts, searchQuery, setSearchQuery, fetchPosts } = usePost();

    useEffect(() => {
        fetchPosts();
        updateVideos();
    }, [searchQuery]);

    const updateVideos = async () => {
        axios.get("http://localhost:8000/update_videos")
            .then(response => {
                console.log(response.data.message);
            })
            .catch(error => {
                console.error("There was an error updating the videos!", error);
            });
    };

    return (
        <>
            <input
                type="text"
                placeholder="Search by title"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                style={{ marginBottom: "20px", padding: "10px", width: "100%" }}
            />
            {posts.length > 0 ? (
                posts.map(post => (
                    <Post key={post.post_id} {...post} />
                ))
            ) : (
                <p>No posts found</p>
            )}
        </>
    );
}