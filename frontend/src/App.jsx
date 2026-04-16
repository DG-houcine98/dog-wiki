import { useState, useEffect } from 'react'
import './App.css'

function App() {
  const [dogs, setDogs] = useState([])
  const [breed, setBreed] = useState('')
  const [description, setDescription] = useState('')
  const [photo, setPhoto] = useState(null)
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(false)
  const [health, setHealth] = useState(null)

  const fetchDogs = () => {
    fetch('/api/dogs')
      .then(res => res.json())
      .then(data => setDogs(data))
      .catch(() => setDogs([]))
  }

  useEffect(() => {
    fetchDogs()
    fetch('/api/health')
      .then(res => res.json())
      .then(data => setHealth(data.status))
      .catch(() => setHealth('error'))
  }, [])

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

    fetch('/api/dogs', { method: 'POST', body: formData })
      .then(res => {
        if (res.ok) {
          setBreed('')
          setDescription('')
          setPhoto(null)
          setPreview(null)
          fetchDogs()
        }
      })
      .finally(() => setLoading(false))
  }

  return (
    <div className="app">
      <header>
        <div className="header-left">
          <div className="logo-row">
            <img src="/datadog.svg" alt="Datadog" className="dd-logo" />
            <h1>Dog Breeds</h1>
          </div>
          <p className="subtitle">Discover and share your favorite breeds</p>
        </div>
        <span className={`badge ${health === 'ok' ? 'badge-ok' : 'badge-error'}`}>
          {health === 'ok' ? 'API Connected' : 'API Offline'}
        </span>
      </header>

      <form className="add-form" onSubmit={handleSubmit}>
        <h2>Add a New Breed</h2>
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
              rows={4}
            />
            <label className="file-upload">
              <input
                type="file"
                accept="image/*"
                onChange={handlePhotoChange}
              />
              <span className="file-upload-label">
                {photo ? photo.name : 'Choose a photo...'}
              </span>
            </label>
            <button type="submit" disabled={loading}>
              {loading ? 'Uploading...' : 'Add Breed'}
            </button>
          </div>
          {preview && (
            <div className="form-preview">
              <img src={preview} alt="Preview" />
            </div>
          )}
        </div>
      </form>

      <section className="gallery">
        <h2>All Breeds <span className="count">{dogs.length}</span></h2>
        {dogs.length === 0 && <p className="empty">No breeds yet. Add one above!</p>}
        <div className="grid">
          {dogs.map(dog => (
            <div key={dog.id} className="card">
              <div className="card-img">
                {dog.photo_url ? (
                  <img src={`/api${dog.photo_url}`} alt={dog.breed} />
                ) : (
                  <div className="no-photo">No Photo</div>
                )}
              </div>
              <div className="card-body">
                <h3>{dog.breed}</h3>
                <p>{dog.description}</p>
                <small>{new Date(dog.created_at).toLocaleDateString()}</small>
              </div>
            </div>
          ))}
        </div>
      </section>

      <footer>
        <img src="/datadog.svg" alt="Datadog" className="dd-footer-logo" />
        <span>Powered by Datadog</span>
      </footer>
    </div>
  )
}

export default App
