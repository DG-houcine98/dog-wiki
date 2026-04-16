import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import './App.css'

function EditDog() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [breed, setBreed] = useState('')
  const [description, setDescription] = useState('')
  const [photo, setPhoto] = useState(null)
  const [preview, setPreview] = useState(null)
  const [existingPhoto, setExistingPhoto] = useState(null)
  const [loading, setLoading] = useState(false)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    fetch(`/api/dogs/${id}`)
      .then(res => res.json())
      .then(data => {
        setBreed(data.breed || '')
        setDescription(data.description || '')
        if (data.photo_url) {
          setExistingPhoto(`/api${data.photo_url}`)
        }
      })
  }, [id])

  const handlePhotoChange = (e) => {
    const file = e.target.files[0]
    setPhoto(file)
    if (file) {
      setPreview(URL.createObjectURL(file))
    } else {
      setPreview(null)
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!breed) return

    setLoading(true)
    const formData = new FormData()
    formData.append('breed', breed)
    formData.append('description', description)
    if (photo) formData.append('photo', photo)

    fetch(`/api/dogs/${id}`, { method: 'PUT', body: formData })
      .then(res => {
        if (res.ok) navigate('/')
      })
      .finally(() => setLoading(false))
  }

  const handleDelete = () => {
    if (!confirm('Delete this breed?')) return
    setDeleting(true)
    fetch(`/api/dogs/${id}`, { method: 'DELETE' })
      .then(res => {
        if (res.ok) navigate('/')
      })
      .finally(() => setDeleting(false))
  }

  const photoSrc = preview || existingPhoto

  return (
    <div className="app">
      <header>
        <div className="header-left">
          <div className="logo-row">
            <img src="/datadog.svg" alt="Datadog" className="dd-logo" />
            <h1>Edit Breed</h1>
          </div>
          <p className="subtitle">
            <a className="back-link" onClick={() => navigate('/')}>Back to all breeds</a>
          </p>
        </div>
      </header>

      <form className="add-form" onSubmit={handleSubmit}>
        <div className="form-grid">
          <div className="form-fields">
            <input
              type="text"
              placeholder="Breed name"
              value={breed}
              onChange={e => setBreed(e.target.value)}
              required
            />
            <textarea
              placeholder="Describe this breed..."
              value={description}
              onChange={e => setDescription(e.target.value)}
              rows={5}
            />
            <label className="file-upload">
              <input
                type="file"
                accept="image/*"
                onChange={handlePhotoChange}
              />
              <span className="file-upload-label">
                {photo ? photo.name : 'Change photo...'}
              </span>
            </label>
            <div className="edit-actions">
              <button type="submit" disabled={loading}>
                {loading ? 'Saving...' : 'Save Changes'}
              </button>
              <button
                type="button"
                className="btn-delete"
                onClick={handleDelete}
                disabled={deleting}
              >
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
          {photoSrc && (
            <div className="form-preview">
              <img src={photoSrc} alt="Preview" />
            </div>
          )}
        </div>
      </form>
    </div>
  )
}

export default EditDog
