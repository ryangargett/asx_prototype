import {useState} from "react";
import {useNavigate} from "react-router-dom";
import axios from "axios";

export default function LoginPage() {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [redirect, setRedirect] = useState(false);
    const navigate = useNavigate();

    async function attemptLogin(ev) {
        ev.preventDefault();
        try {
            const response = await axios.post("http://localhost:8000/login", {
                username,
                password
            });
            alert(response.data.message);

            localStorage.setItem("token", response.data.access_token);
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

    if (redirect) {
        navigate("/");
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