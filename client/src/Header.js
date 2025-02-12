import { Link, useNavigate } from 'react-router-dom';
import { useUser } from './context/UserContext';
import { Twitter, Search, ChevronDown } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';
import axios from 'axios';

export default function Header() {
    const { username, elevation, setUsername, setElevation } = useUser();
    const navigate = useNavigate();
    const [isUserDropdownOpen, setIsUserDropdownOpen] = useState(false);
    const [isMaterialsDropdownOpen, setIsMaterialsDropdownOpen] = useState(false);
    const userDropdownRef = useRef(null);
    const materialsDropdownRef = useRef(null);

    useEffect(() => {
        const handleClickOutside = (event) => {
            if (userDropdownRef.current && !userDropdownRef.current.contains(event.target)) {
                setIsUserDropdownOpen(false);
            }
            if (materialsDropdownRef.current && !materialsDropdownRef.current.contains(event.target)) {
                setIsMaterialsDropdownOpen(false);
            }
        };

        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

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
        <div className="header-container">
            <div className="header-top">
                <Link to="/" className="header-logo">
                    FINANCIAL WEBSITE
                </Link>
                <div className="search-container">
                    <div className="search-wrapper">
                        <Search className="search-icon" size={20} />
                        <input
                            type="text"
                            placeholder="Search by keyword or code"
                            className="search-input"
                        />
                    </div>
                </div>
            </div>

            <div className="nav-container">
                <nav className="main-nav">
                    <div className="dropdown" ref={materialsDropdownRef}>
                        <button 
                            className="dropdown-trigger"
                            onClick={() => setIsMaterialsDropdownOpen(!isMaterialsDropdownOpen)}
                        >
                            Materials
                            <ChevronDown size={16} className="dropdown-icon" />
                        </button>
                        {isMaterialsDropdownOpen && (
                            <div className="dropdown-menu">
                                <Link to="/materials/iron" className="dropdown-item">Iron</Link>
                                <Link to="/materials/oil" className="dropdown-item">Oil</Link>
                                <Link to="/materials/gold" className="dropdown-item">Gold</Link>
                                <Link to="/materials/silver" className="dropdown-item">Silver</Link>
                                <Link to="/materials/copper" className="dropdown-item">Copper</Link>
                                <Link to="/materials/lithium" className="dropdown-item">Lithium</Link>
                                <Link to="/materials/uranium" className="dropdown-item">Uranium</Link>
                            </div>
                        )}
                    </div>
                    <Link to="/energy" className="nav-link">
                        Energy
                    </Link>
                    <Link to="/stocks" className="nav-link">
                        Stocks
                    </Link>
                    <Link to="/videos" className="nav-link">
                        Videos
                    </Link>
                </nav>
                
                <div className="user-controls">
                    {elevation === "admin" && (
                        <Link to="/create" className="admin-button">
                            Create Post
                        </Link>
                    )}
                    <a href="https://twitter.com" 
                       target="_blank" 
                       rel="noopener noreferrer" 
                       className="social-link">
                        <Twitter size={20} />
                    </a>
                    {username ? (
                        <div className="dropdown" ref={userDropdownRef}>
                            <button 
                                className="user-dropdown-trigger"
                                onClick={() => setIsUserDropdownOpen(!isUserDropdownOpen)}
                            >
                                Hello, {username}
                                <ChevronDown size={16} className="dropdown-icon" />
                            </button>
                            {isUserDropdownOpen && (
                                <div className="dropdown-menu">
                                    <span onClick={logoutUser} className="user-dropdown-item logout-option">
                                        Logout
                                    </span>
                                </div>
                            )}
                        </div>
                    ) : (
                        <Link to="/login" className="auth-link">
                            Login
                        </Link>
                    )}
                </div>
            </div>

            <div className="ticker-container">
                {/* Ticker content will go here */}
            </div>
        </div>
    );
}