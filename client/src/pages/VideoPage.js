import { useEffect, useState } from "react";
import axios from "axios";

export default function VideoPage() {
    const [videos, setVideos] = useState([]);
    const [selectedVideo, setSelectedVideo] = useState(null);

    useEffect(() => {
        axios.get("http://localhost:8000/cached_videos")
            .then(response => {
                setVideos(response.data.videos);
            })
            .catch(error => {
                console.error("There was an error fetching the videos!", error);
            });
    }, []);

    return (
        <div className="videos-page">
            <h1 className="videos-title">Videos</h1>
            <div className="videos-grid">
                {videos.map(video => (
                    <div key={video.snippet.resourceId.videoId} className="video-item" onClick={() => setSelectedVideo(video.snippet.resourceId.videoId)}>
                        <img src={video.snippet.thumbnails.medium.url} alt={video.snippet.title} className="video-thumbnail" />
                        <h3 className="video-title">{video.snippet.title}</h3>
                    </div>
                ))}
            </div>
            {selectedVideo && (
                <div className="video-player-overlay" onClick={() => setSelectedVideo(null)}>
                    <div className="video-player-container" onClick={e => e.stopPropagation()}>
                        <div className="video-player">
                            <iframe
                                width="100%"
                                height="100%"
                                src={`https://www.youtube.com/embed/${selectedVideo}?vq=hd1080`}
                                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                                allowFullScreen
                                title="YouTube video player"
                            ></iframe>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
