import {useEffect, useState} from "react";
import {Link, useNavigate} from 'react-router-dom';
import axios from "axios";

export default function Header() {

    const [username, setUsername] = useState(null);
    const {navigate} = useNavigate();

    async function verifyToken() {
        const token = localStorage.getItem("token");
        if (token) {
            try {
                // Verify the token
                const response = await axios.get(`http://localhost:8000/verify?token=${token}`);
                alert(response.data.message);
                setUsername(response.data.username);
            } catch (error) {
                localStorage.removeItem("token");
                alert("Authentication failed, please login");
                navigate("/login");
            }
        } else {
            alert("An unexpected error occured, please login");
            navigate("/login");
        }
    }

    useEffect(() => {
        const token = localStorage.getItem("token");
        if (token) {
            verifyToken();
        }
    }, []);

    return (    
        <header>
            <Link to="/" className="logo">ASX Blog</Link>
            <nav>
                {username && (
                    <>
                        <Link to="/profile">{username}</Link>
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