import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Editor from "../Editor";
import "react-quill-new/dist/quill.snow.css";
import axios from 'axios';
import { fileTypeFromBuffer } from 'file-type';

export default function CreatePostPage() {
    const [title, setTitle] = useState("");
    const [cover_image, setCoverImage] = useState(null);
    const [coverImageUrl, setCoverImageUrl] = useState("http://localhost:8000/uploads/GENERIC/PLACEHOLDER.svg");
    const [content, setContent] = useState("");
    const [pdf, setPdf] = useState(null);
    const [postID, setPostID] = useState(null);

    const [dragging, setDragging] = useState(false);
    const [loading, setLoading] = useState(false);
    const coverImageInputRef = useRef(null);

    const [profiles, setProfiles] = useState([]);
    const [selectedProfile, setSelectedProfile] = useState("");
    const [userPrompt, setUserPrompt] = useState("");
    const [promptProfile, setPromptProfile] = useState({});

    const navigate = useNavigate();

    const fetchProfiles = async () => {
        try {
            const response = await axios.get("http://localhost:8000/profiles");
            setProfiles(response.data.profiles);
        } catch (error) {
            console.error("Error fetching profiles:", error);
        }
    };

    useEffect(() => {
        fetchProfiles();
    }, []);

    const handleProfileChange = async (ev) => {
        const profileId = ev.target.value;
        setSelectedProfile(profileId);
    
        if (promptProfile[profileId]) {
            setUserPrompt(promptProfile[profileId]);
        } else {
            try {
                const response = await axios.post("http://localhost:8000/get_profile", { profile_id: profileId });
                setUserPrompt(response.data.profile.prompt);
                setPromptProfile(prevState => ({ ...prevState, [profileId]: response.data.profile.prompt }));
            } catch (error) {
                console.error("Error fetching profile:", error);
            }
        }
    };

    async function createPost(ev) {
        ev.preventDefault();

        const postData = new FormData();
        postData.append("title", title);
        postData.append("content", content);
        postData.append("cover_image_url", coverImageUrl); // Include the cover image URL
        if (cover_image) {
            postData.append("cover_image", cover_image);
        }
        if (postID) {
            postData.append("post_id", postID);
        }

        console.log(postData);

        try {
            console.log(cover_image);
            const response = await axios.post("http://localhost:8000/create",
                postData,
                { headers: {
                        "Content-Type": "multipart/form-data"
                }
            });

            console.log(response.data.message);
        } catch (error) {
            if (error.response && error.response.data && error.response.data.detail) {
                alert(error.response.data.detail);
            } else {
                alert("An unexpected error occurred please try again later");
            }
        }
        navigate("/");
    }

    const handleDragOver = (ev) => {
        ev.preventDefault();
        setDragging(true);
    };

    const handleDragLeave = () => {
        setDragging(false);
    };

    const handleDrop = async (ev) => {
        ev.preventDefault();
        setDragging(false);
        setLoading(true);
        const file = ev.dataTransfer.files[0];
        
        console.log(userPrompt);

        // Check the file type
        const buffer = await file.arrayBuffer();
        const fileType = await fileTypeFromBuffer(buffer);
        const mimeType = fileType ? fileType.mime : null;
        if (!mimeType || (!mimeType.startsWith("application/pdf") && !mimeType.startsWith("video/"))) {
            alert("Invalid file type. Please upload a PDF or video file.");
            setLoading(false);
            return;
        }
    
        const formData = new FormData();
        formData.append("file", file);
        formData.append("user_prompt", userPrompt);

        console.log(file);
        console.log(userPrompt);
        
        try {
            const response = await axios.post("http://localhost:8000/autofill", formData, {
                headers: {
                    "Content-Type": "multipart/form-data"
                }
            });
            setLoading(false);
            setTitle(response.data.title);
            setContent(response.data.content);
            setCoverImageUrl(response.data.cover_image);
            setPostID(response.data.post_id);
            console.log(postID);
        } catch (error) {
            alert("An unexpected error occurred when attempting autofill, please try again later: " + error);
            setLoading(false);
        }
    };

    const handleAddProfile = async () => {
        try {
            const response = await axios.post("http://localhost:8000/add_profile", { prompt: userPrompt });
            console.log(response.data.message);
            await fetchProfiles();
            setUserPrompt("");
        } catch (error) {
            console.error("Error adding profile:", error);
        }
    };

    return (
        <div className="create-post">
            {loading && (
                <div className="loader-overlay">
                        <div className="loader-spinner"></div>
                </div>
            )}
            <form onSubmit={createPost}>
            <div>
                    <label htmlFor="profile-select">Select a Prompt Profile:</label>
                    <select
                        id="profile-select"
                        value={selectedProfile}
                        onChange={handleProfileChange}
                    >
                        <option value="">Select a profile</option>
                        {profiles.map(profile => (
                            <option key={profile.name} value={profile.name}>
                                {profile.name}
                            </option>
                        ))}
                    </select>
                </div>
                <div>
                    <label htmlFor="user-prompt">User Prompt:</label>
                    <div className="prompt-content">
                        <Editor 
                            onChange={setUserPrompt} value={userPrompt}>
                        </Editor>
                    </div>
                </div>
                <button type="button" onClick={handleAddProfile}>Add</button>
                <h1>Autofill from PDF</h1>
                <div 
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    style={{
                        border: dragging ? "2px dashed #000" : "2px solid #ccc",
                        padding: "20px",
                        marginTop: "10px",
                        textAlign: "center"
                    }}
                >
                    {pdf ? pdf.name : "Drag and drop a PDF file here or click to upload"}
                </div>
                <div>
                    <h1>OR</h1>
                    <h1>Create manually</h1>
                </div>
                <input 
                    type="text" 
                    placeholder={"Title"} 
                    value={title} 
                    onChange={ev => setTitle(ev.target.value)} 
                />
                <input 
                    type="file"
                    ref={coverImageInputRef}
                    onChange={ev => {
                        setCoverImage(ev.target.files[0]);
                        setCoverImageUrl(URL.createObjectURL(ev.target.files[0]));
                    }}
                />
                {coverImageUrl && (
                    <div>
                        <img src={coverImageUrl} alt="Cover" style={{ width: "100px", height: "100px" }} />
                    </div>
                )}
                <div className="article-content">
                    <Editor 
                        onChange={setContent} value={content}>
                    </Editor>
                </div>
                <button style={{marginTop:"5px"}}>Create Post</button>
            </form>
        </div>
    )
}