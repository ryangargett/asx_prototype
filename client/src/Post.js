import TimeAgo from 'javascript-time-ago';
import enAU from 'javascript-time-ago/locale/en-AU';
import ReactTimeAgo from 'react-time-ago';
import { Link } from 'react-router-dom';

TimeAgo.addLocale(enAU)

export default function Post({post_id, title, cover_image, modified_at}) {
    const coverPath = `http://localhost:8000/uploads/${post_id}/${cover_image}`;
    console.log(modified_at);
    const modifiedAt = new Date(modified_at);
    const localModifiedAt = new Date(modifiedAt.getTime() - (modifiedAt.getTimezoneOffset() * 60000));
    console.log(localModifiedAt);

    return (
        <Link to={`/post/${post_id}`} className="post" id={post_id}>
            <div className="post-img">
                <img 
                    src={coverPath}
                    alt={title}
                /> 
            </div>
            <div className="post-info">
                <h1 className="post-title">{title}</h1>
                <h3 className="post-date">
                    Posted: <ReactTimeAgo date={localModifiedAt} locale="en-AU"/>
                </h3>
            </div>
        </Link>
    );
}