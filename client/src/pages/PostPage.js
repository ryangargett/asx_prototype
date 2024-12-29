import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useUser } from '../context/UserContext'
import axios from "axios"


export default function PostPage() {

    const [post, setPost] = useState(null)
    const params = useParams()
    const { elevation } = useUser();

    console.log(params)

    useEffect(() => {
        axios.get(`http://localhost:8000/post/${params.id}`)
            .then(response => {
                console.log(response.data.message)
                console.log(response.data.post)
                setPost(response.data.post)
            })
            .catch(error => {
                console.error("There was an error fetching the post!", error)
            })
    }, [params.id])

    if (!post) {
        return <div>Loading...</div>;
    }

    return (
        <div className="post-page">
            <div className="post-img">
                <img src={`http://localhost:8000/uploads/${post.post_id}/${post.cover_image}`} alt={post.title} />
            </div>
            <h1 className="post-title">
                {post.title}
            </h1>
            {elevation === "admin" && (
                <Link to={`/edit/${post.post_id}`} className="edit-post">Edit Post</Link>
            )}
            <div className="post-content" dangerouslySetInnerHTML={{__html:post.content}}></div>
        </div>
    )

}