import TimeAgo from 'javascript-time-ago';
import enAU from 'javascript-time-ago/locale/en-AU';
import ReactTimeAgo from 'react-time-ago';
import { Link } from 'react-router-dom';
import { usePost } from './context/PostContext';

TimeAgo.addLocale(enAU)

export default function Post({ post_id, title, cover_image, modified_at }) {
    const { searchQuery } = usePost();
    const isDefaultImg = cover_image.includes("GENERIC/PLACEHOLDER.svg");
    const imgURL = isDefaultImg 
        ? "http://localhost:8000/uploads/GENERIC/PLACEHOLDER.svg"
        : cover_image;
    const modifiedAt = new Date(modified_at);
    const localModifiedAt = new Date(modifiedAt.getTime() - (modifiedAt.getTimezoneOffset() * 60000));

    const getSearchMatch = (text, highlight) => {
        const parts = text.split(new RegExp(`(${highlight})`, "gi"));
        return parts.map((part, index) =>
            part.toLowerCase() === highlight.toLowerCase() ? (
                <span key={index} style={{ backgroundColor: "lightblue" }}>{part}</span>
            ) : (
                part
            )
        );
    };

    return (
        <Link to={`/post/${post_id}`} className="post" id={post_id}>
            <div className="post-img">
                <img src={imgURL} alt={title} />
            </div>
            <div className="post-info">
                <h1 className="post-title">{getSearchMatch(title, searchQuery)}</h1>
                <h3 className="post-date">
                    Posted: <ReactTimeAgo date={localModifiedAt} locale="en-AU" />
                </h3>
            </div>
        </Link>
    );
}