import {useState} from "react";
import axios from "axios";

export default function RegisterPage() {
    const [username, setUsername] = useState("");
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    
    async function attemptRegister(ev) {
        ev.preventDefault();
        try {
            const response = await axios.post("http://localhost:8000/register", {
                username,
                email,
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
        <form className = "register" onSubmit={attemptRegister}>
            <h1>Register</h1>
            <input type="text"
                placeholder="Username" 
                value={username} 
                onChange={ev => setUsername(ev.target.value)}
            />
             <input type="text"
                placeholder="Email"
                value={email} 
                onChange={ev => setEmail(ev.target.value)}
            />
            <input type="text"
                placeholder="Password" 
                value={password} 
                onChange={ev => setPassword(ev.target.value)}
            />
            <button>Register</button>
        </form> 
    )
}