import { createContext, useState, useContext, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';

const PostContext = createContext({
    posts: [],
    searchQuery: '',
    setPosts: () => {},
    setSearchQuery: () => {},
    fetchPosts: () => {}
});

export const PostProvider = ({ children }) => {
    const [posts, setPosts] = useState([]);
    const [searchQuery, setSearchQuery] = useState(localStorage.getItem('searchQuery') || '');

    const fetchPosts = async () => {
        try {
            const response = await axios.get("http://localhost:8000/posts", {
                params: { search: searchQuery || "" }
            });
            setPosts(response.data.posts);
        } catch (error) {
            console.error("There was an error fetching the posts!", error);
        }
    };

    useEffect(() => {
        fetchPosts();
    }, [searchQuery]);

    useEffect(() => {
        localStorage.setItem('searchQuery', searchQuery);
    }, [searchQuery]);

    return (
        <PostContext.Provider value={{ posts, searchQuery, setPosts, setSearchQuery, fetchPosts }}>
            {children}
        </PostContext.Provider>
    );
};

export const usePost = () => {
    return useContext(PostContext);
};