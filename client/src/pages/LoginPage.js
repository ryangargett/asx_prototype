import {useState} from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";

export default function LoginPage() {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [redirect, setRedirect] = useState(false);

    async function attemptLogin(ev) {
        ev.preventDefault();
        try {
            const response = await axios.post("http://localhost:8000/login", {
                username,
                password
            });
            alert(response.data.message);

            localStorage.setItem("token", data.access_token);
            // Redirect to the home page if login successful
            setRedirect(true);

        } catch (error) {
            if (error.response && error.response.data && error.response.data.detail) {
                alert(error.response.data.detail);
            } else {
                alert("An unexpected error occurred");
            }
        }
    }

    async function verifyToken() {
        const token = localStorage.getItem("token");
        if (token) {
            try {
                // Verify the token
                const response = await axios.post(`http://localhost:8000/verify/${token}`, {
                    token
                });
                alert(response.data.message);
            } catch (error) {
                localStorage.removeItem("token");
                navigate("/login"); // Authentication failed, remove local token for security
            }
        } else {
            navigate("/login");
        }
    }

    useEffect(() => {
        const token = localStorage.getItem("token");
        if (token) {
            verifyToken(token);
        }
    }, []);

    if (redirect) {
        return <Navigate to={"/"} />;
    }

    return (
        <form className = "login" onSubmit={attemptLogin}>
            <h1>Login</h1>
            <input type="text" 
                placeholder="Username"
                value={username}
                onChange={ev => setUsername(ev.target.value)}
            />
            <input type="text"
                placeholder="Password" 
                value={password} 
                onChange={ev => setPassword(ev.target.value)}
            />
            <button>Login</button>
        </form> 
    )
}