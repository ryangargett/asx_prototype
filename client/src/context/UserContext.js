import { createContext, useState, useContext, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';

// Create a context with default values
const UserContext = createContext({
    username: null,
    elevation: null,
    setUsername: () => {},
    setElevation: () => {},
    verifyToken: () => {}
});

export const UserProvider = ({ children }) => {
    const [username, setUsername] = useState(null);
    const [elevation, setElevation] = useState(null);

    const navigate = useNavigate();

    const verifyToken = async () => {
        try {
            const response = await axios.get("http://localhost:8000/verify", {
                withCredentials: true
            });
            setUsername(response.data.username);
            setElevation(response.data.elevation);
            console.log("Elevation", response.data.elevation);
        } catch (error) {
            alert("Authentication failed, please login");
            setUsername(null);
            setElevation(null);
            navigate("/login");
        }
    };

    useEffect(() => {
        verifyToken();
    }, []);

    return (
        <UserContext.Provider value={{ username, elevation, setUsername, setElevation, verifyToken }}>
            {children}
        </UserContext.Provider>
    );
};

// Custom hook to use the UserContext
export const useUser = () => {
    return useContext(UserContext);
};