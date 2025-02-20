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
    const [tickerQuery, setTickerQuery] = useState("");
    const [tickerResults, setTickerResults] = useState([]);
    const userDropdownRef = useRef(null);
    const materialsDropdownRef = useRef(null);
    const tickerRef = useRef(null);

    useEffect(() => {
        const handleClickOutside = (event) => {
            if (userDropdownRef.current && !userDropdownRef.current.contains(event.target)) {
                setIsUserDropdownOpen(false);
            }
            if (materialsDropdownRef.current && !materialsDropdownRef.current.contains(event.target)) {
                setIsMaterialsDropdownOpen(false);
            }
            if (tickerRef.current && !tickerRef.current.contains(event.target)) {
                setTickerResults([]);
            }
        };

        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    useEffect(() => {
        if (tickerQuery.length > 1) {
            fetchTickers(tickerQuery);
        } else {
            setTickerResults([]);
        }
    }, [tickerQuery]);

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

    async function fetchTickers(query) {
        try {
            const response = await axios.post("http://localhost:8000/get_tickers", { search_query: query });
            setTickerResults(response.data.tickers);
        } catch (error) {
            console.error("Error fetching tickers:", error);
        }
    }

    const handleTickerChange = (event) => {
        setTickerQuery(event.target.value);
    };

    return (
        <div className="header-container">
            <div className="header-top">
                <Link to="/" className="header-logo">
                    FINANCIAL WEBSITE
                </Link>
                <div className="search-container">
                    <div className="search-wrapper" ref={tickerRef}>
                        <Search className="search-icon" size={20} />
                        <input
                            type="text"
                            placeholder="Search by keyword or code"
                            className="search-input"
                            value={tickerQuery}
                            onChange={handleTickerChange}
                        />
                        {tickerResults.length > 0 && (
                            <div className="search-results-dropdown">
                                {tickerResults.map((result) => (
                                    <div 
                                        key={result.ticker} 
                                        className="search-result-item"
                                        onClick={() => {
                                            navigate(`/stocks/${result.ticker.toLowerCase()}`);
                                            setTickerQuery("");
                                            setTickerResults([]);
                                        }}
                                    >
                                        <span className="search-result-ticker">{result.ticker}</span>
                                        <span className="search-result-company">{result.company_name}</span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>

            <div className="nav-container">
                <nav className="main-nav">
                    <div className="materials-dropdown" ref={materialsDropdownRef}>
                        <button 
                            className="materials-dropdown-trigger"
                            onClick={() => setIsMaterialsDropdownOpen(!isMaterialsDropdownOpen)}
                        >
                            Materials
                            <ChevronDown size={16} className="dropdown-icon" />
                        </button>
                        {isMaterialsDropdownOpen && (
                            <div className="materials-dropdown-menu">
                                <Link to="/materials/iron" className="materials-dropdown-item">Iron</Link>
                                <Link to="/materials/oil" className="materials-dropdown-item">Oil</Link>
                                <Link to="/materials/gold" className="materials-dropdown-item">Gold</Link>
                                <Link to="/materials/silver" className="materials-dropdown-item">Silver</Link>
                                <Link to="/materials/copper" className="materials-dropdown-item">Copper</Link>
                                <Link to="/materials/lithium" className="materials-dropdown-item">Lithium</Link>
                                <Link to="/materials/uranium" className="materials-dropdown-item">Uranium</Link>
                            </div>
                        )}
                    </div>
                    <Link to="/energy" className="nav-link">Energy</Link>
                    <Link to="/stocks" className="nav-link">Stocks</Link>
                    <Link to="/videos" className="nav-link">Videos</Link>
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
                        <div className="user-dropdown" ref={userDropdownRef}>
                            <button 
                                className="user-dropdown-trigger"
                                onClick={() => setIsUserDropdownOpen(!isUserDropdownOpen)}
                            >
                                Hello, {username}
                                <ChevronDown size={16} className="dropdown-icon" />
                            </button>
                            {isUserDropdownOpen && (
                                <div className="user-dropdown-menu">
                                    <span onClick={logoutUser} className="user-dropdown-item">
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