# Keep user data out of the repository

djsupport keeps OAuth credentials, source-library data, matching knowledge, Corrections, Transfer manifests, playlist-management state, reports, and user-derived regression data in local application storage rather than in the repository. The repository contains the software, documentation, storage schemas and migrations, synthetic fixtures, and only those regression cases a user explicitly exports for contribution; this protects personal data and lets every installation maintain independent Spotify and music-library state.
