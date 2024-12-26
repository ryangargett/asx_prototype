import {useState} from "react";
import axios from "axios";

export default function LoginPage() {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");

    async function attemptLogin(ev) {
        ev.preventDefault();
        try {
            const response = await axios.post("http://localhost:8000/login", {
                username,
                password
            });
            alert(response.data.message);
        } catch (error) {
            if (error.response && error.response.data && error.response.data.detail) {
                alert(error.response.data.detail);
            } else {
                alert("An unexpected error occurred");
            }
        }
    }

    return (
        <form className = "login">
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