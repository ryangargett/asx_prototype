import { Link, useNavigate } from 'react-router-dom';
import { useUser } from './context/UserContext';
import axios from 'axios';

export default function Header() {
    const { username, elevation, setUsername, setElevation } = useUser();
    const navigate = useNavigate();

    async function logoutUser() {
        try {
            const response = await axios.post("http://localhost:8000/logout", {}, {
                withCredentials: true
            });
            alert(response.data.message);
            setUsername(null);
            setElevation(null);
            navigate("/");
        } catch (error) {
            alert("An unexpected error occurred");
        }
    }

    return (    
        <header>
            <Link to="/" className="logo">ASX Blog</Link>
            <nav>
                {username && (
                    <>
                        <Link to="/profile">Welcome, {username}!</Link>
                        {elevation === "admin" && <Link to="/create">Create Post</Link>}
                        <Link to="/videos">Videos</Link>
                        <Link to="/" onClick={logoutUser}>Logout</Link>
                    </>
                )}
                {!username && (
                    <>
                        <Link to="/login">Login</Link>
                        <Link to="/register">Register</Link>
                    </>
                )}               
            </nav>
        </header>
    );
}