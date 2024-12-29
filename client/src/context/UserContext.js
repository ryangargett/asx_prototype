import { createContext, useState, useContext, useEffect } from 'react';
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

    const verifyToken = async () => {
        try {
            const response = await axios.get("http://localhost:8000/verify", {
                withCredentials: true
            });
            setUsername(response.data.username);
            setElevation(response.data.elevation);
            console.log("Elevation", response.data.elevation);
        } catch (error) {
            console.log("Authentication failed, please login");
        }
    };

    useEffect(() => {
        if (!username) {
            verifyToken();
        }
    }, [username]);

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