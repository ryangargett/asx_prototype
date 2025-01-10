import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useUser } from "../context/UserContext"
import axios from "axios"

export default function PostPage() {

    const [post, setPost] = useState(null)
    const [hasPDF, setHasPDF] = useState(false)
    const params = useParams()
    const { elevation } = useUser();

    console.log(params)

    useEffect(() => {
        axios.get(`http://localhost:8000/post/${params.id}`)
            .then(response => {
                console.log(response.data.message)
                console.log(response.data.post)
                setPost(response.data.post)
                checkPDFExists(response.data.post.post_id)
            })
            .catch(error => {
                console.error("There was an error fetching the post!", error)
            })
    }, [params.id])

    const checkPDFExists = async (post_id) => {
        try {
            const response = await axios.head(`http://localhost:8000/uploads/${post_id}/${post_id}.pdf`)
            if (response.status === 200) {
                setHasPDF(true)
            }
        } catch (error) {
            setHasPDF(false)
        }
    }

    if (!post) {
        return <div>Loading...</div>;
    }

    const isDefaultImg = post.cover_image.includes("GENERIC/PLACEHOLDER.svg")
    const imgURL = isDefaultImg 
        ? "http://localhost:8000/uploads/GENERIC/PLACEHOLDER.svg"
        : `http://localhost:8000/uploads/${post.post_id}/${post.cover_image}?t=${new Date().getTime()}`;

    return (
        <div className="post-page">
            <div className="post-img">
                <img src={imgURL} alt={post.title} />
            </div>
            <h1 className="post-title">
                {post.title}
            </h1>
            {elevation === "admin" && (
                <Link to={`/edit/${post.post_id}`} className="edit-post">Edit Post</Link>
            )}
            <div className="post-content" dangerouslySetInnerHTML={{__html:post.content}}></div>
            <div className="pdf-header">
                <h1>Raw file:</h1>
            </div>
            {hasPDF && (
                <div className="pdf-content">
                    <iframe src={`http://localhost:8000/uploads/${post.post_id}/${post.post_id}.pdf`} width="100%" height="600px"></iframe>
                </div>
            )}
        </div>
    )

}