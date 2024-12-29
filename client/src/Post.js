import TimeAgo from 'javascript-time-ago';
import en from 'javascript-time-ago/locale/en';
import enAU from 'javascript-time-ago/locale/en-AU';
import ReactTimeAgo from 'react-time-ago';

TimeAgo.addLocale(enAU)

export default function Post({post_id, title, cover_image, modified_at}) {
    const coverPath = `http://localhost:8000/uploads/${post_id}/${cover_image}`;
    console.log(modified_at);
    const modifiedAt = new Date(modified_at);
    const localModifiedAt = new Date(modifiedAt.getTime() - (modifiedAt.getTimezoneOffset() * 60000));
    console.log(localModifiedAt);

    return (
        <div className="post" id={post_id}>
            <div className="post-img">
                <img 
                    src={coverPath}  
                /> 
            </div>
            <div className="post-info">
                <h2>{title}</h2>
                <h3>
                    Posted: <ReactTimeAgo date={localModifiedAt} locale="en-AU"/>
                </h3>
            </div>
        </div>
    );
}