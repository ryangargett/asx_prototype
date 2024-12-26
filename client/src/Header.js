import {useEffect, useState} from "react";
import {Link, useNavigate} from 'react-router-dom';
import axios from "axios";

export default function Header() {

    const [username, setUsername] = useState(null);
    const navigate = useNavigate();

    async function verifyToken() {
        const token = localStorage.getItem("token");
        console.log("Token", token);
        if (token) {
            try {
                const response = await axios.get("http://localhost:8000/verify", {
                        withCredentials: true
                });
                alert(response.data.message);
                setUsername(response.data.username);
            } catch (error) {
                alert("Authentication failed, please login");
            }
        } else {
            alert("An unexpected error occured, please login");
            navigate("/login");
        }
    }

    async function logoutUser() {
        try {
            const response = await axios.post("http://localhost:8000/logout", {}, {
                withCredentials: true
            });
            alert(response.data.message);
            setUsername(null);
            navigate("/");
        } catch (error) {
            alert("An unexpected error occurred");
        }
    }

    useEffect(() => {
        verifyToken();
    }, []);


    return (    
        <header>
            <Link to="/" className="logo">ASX Blog</Link>
            <nav>
                {username && (
                    <>
                        <Link to="/profile">{username}</Link>
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