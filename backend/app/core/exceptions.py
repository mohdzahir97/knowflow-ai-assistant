"""Application-level exception hierarchy.

Services and providers raise these instead of leaking library-specific
exceptions (SQLAlchemy errors, HTTP client errors, ChromaDB errors, etc.)
so the API layer can translate them into a consistent response shape
without depending on infrastructure details.
"""


class AppError(Exception):
    """Base class for all application exceptions."""

    status_code: int = 500
    message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None):
        self.message = message or self.message
        super().__init__(self.message)


class AuthenticationError(AppError):
    status_code = 401
    message = "Authentication failed."


class InvalidCredentialsError(AuthenticationError):
    message = "Invalid email or password."


class TokenError(AuthenticationError):
    message = "Invalid or expired token."


class UserAlreadyExistsError(AppError):
    status_code = 409
    message = "A user with this email already exists."


class AuthorizationError(AppError):
    status_code = 403
    message = "You do not have permission to perform this action."


class ResourceNotFoundError(AppError):
    status_code = 404
    message = "The requested resource was not found."


class ValidationAppError(AppError):
    status_code = 422
    message = "Validation failed."


class UnsupportedFileTypeError(AppError):
    status_code = 415
    message = "Unsupported file type."


class FileTooLargeError(AppError):
    status_code = 413
    message = "Uploaded file exceeds the maximum allowed size."


class CorruptedFileError(AppError):
    status_code = 422
    message = "The uploaded file could not be processed."


class EmptyDocumentError(AppError):
    status_code = 422
    message = "The uploaded document contains no extractable text."


class NoDocumentsFoundError(AppError):
    status_code = 404
    message = "No documents have been uploaded yet."


class NoMatchingContextError(AppError):
    status_code = 200
    message = "I couldn't find that information in the uploaded documents."


class InvalidProviderError(AppError):
    status_code = 400
    message = "Invalid or unsupported provider specified."


class InvalidModelError(AppError):
    status_code = 400
    message = "Invalid or unsupported model specified."


class MissingAPIKeyError(AppError):
    status_code = 500
    message = "The requested provider is not configured on the server."


class ProviderError(AppError):
    status_code = 502
    message = "The AI provider returned an error."


class RateLimitError(AppError):
    status_code = 429
    message = "The AI provider rate limit was exceeded. Please try again shortly."


class EmbeddingError(AppError):
    status_code = 502
    message = "Failed to generate embeddings."


class VectorStoreError(AppError):
    status_code = 502
    message = "Vector store operation failed."


class DatabaseError(AppError):
    status_code = 500
    message = "A database error occurred."


class NetworkError(AppError):
    status_code = 503
    message = "A network error occurred while contacting an upstream service."
