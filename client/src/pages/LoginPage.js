import {useState} from "react";
import {useNavigate} from "react-router-dom";
import axios from "axios";
import { useUser } from "../context/UserContext";

export default function LoginPage() {
    const [username, setLocalUsername] = useState("");
    const { setUsername, setElevation } = useUser();
    const [password, setPassword] = useState("");
    const navigate = useNavigate();

    async function attemptLogin(ev) {
        ev.preventDefault();
        try {
            const params = new URLSearchParams();
            params.append('username', username);
            params.append('password', password);

            const response = await axios.post("http://localhost:8000/login", params, {
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                withCredentials: true
            });
            console.log(response.data);
            setUsername(response.data.username);
            setElevation(response.data.elevation);
            navigate("/");
            // Redirect to the home page if login successful
            navigate("/")
        } catch (error) {
            if (error.response && error.response.data && error.response.data.detail) {
                alert(error.response.data.detail);
            } else {
                alert("An unexpected error occurred");
            }
        }
    }

    return (
        <form className="login" onSubmit={attemptLogin}>
            <h1>Login</h1>
            <input type="text" 
                placeholder="Username"
                value={username}
                onChange={ev => setLocalUsername(ev.target.value)}
            />
            <input type="password"
                placeholder="Password" 
                value={password} 
                onChange={ev => setPassword(ev.target.value)}
            />
            <button>Login</button>
        </form> 
    )
}