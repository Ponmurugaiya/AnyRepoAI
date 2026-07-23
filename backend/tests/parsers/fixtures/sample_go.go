// Package api provides sample Go code for parser tests.
// Exercises struct, interface, function, method, import, and Gin route extraction.
package api

import (
	"fmt"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
)

// MaxPageSize is the maximum number of results per page.
const MaxPageSize = 100

// defaultTimeout is the default HTTP client timeout in seconds.
var defaultTimeout = 30

// Role represents a user role in the system.
type Role string

const (
	RoleAdmin Role = "admin"
	RoleUser  Role = "user"
	RoleGuest Role = "guest"
)

// User represents an application user.
type User struct {
	ID    int64  `json:"id"`
	Name  string `json:"name"`
	Email string `json:"email"`
	Role  Role   `json:"role"`
}

// UserRepository defines the data access contract for users.
type UserRepository interface {
	FindByID(id int64) (*User, error)
	FindAll() ([]*User, error)
	Save(user *User) (*User, error)
	DeleteByID(id int64) error
}

// UserService implements business logic for user management.
type UserService struct {
	repo UserRepository
}

// NewUserService creates a new UserService.
func NewUserService(repo UserRepository) *UserService {
	return &UserService{repo: repo}
}

// GetUser retrieves a user by ID.
func (s *UserService) GetUser(id int64) (*User, error) {
	user, err := s.repo.FindByID(id)
	if err != nil {
		return nil, fmt.Errorf("GetUser: %w", err)
	}
	return user, nil
}

// CreateUser creates a new user with the given attributes.
func (s *UserService) CreateUser(name, email string, role Role) (*User, error) {
	user := &User{Name: name, Email: email, Role: role}
	return s.repo.Save(user)
}

// validateEmail returns true if the email address has a valid format.
func validateEmail(email string) bool {
	return len(email) > 3 && contains(email, "@")
}

// contains checks if s contains substr.
func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(substr) == 0 ||
		func() bool {
			for i := 0; i <= len(s)-len(substr); i++ {
				if s[i:i+len(substr)] == substr {
					return true
				}
			}
			return false
		}())
}

// UserHandler holds HTTP handler dependencies.
type UserHandler struct {
	service *UserService
}

// NewUserHandler creates a new UserHandler.
func NewUserHandler(service *UserService) *UserHandler {
	return &UserHandler{service: service}
}

// RegisterRoutes registers all user-related routes on a Gin router.
func (h *UserHandler) RegisterRoutes(r *gin.Engine) {
	r.GET("/api/users", h.ListUsers)
	r.GET("/api/users/:id", h.GetUser)
	r.POST("/api/users", h.CreateUser)
	r.DELETE("/api/users/:id", h.DeleteUser)
}

// ListUsers handles GET /api/users.
func (h *UserHandler) ListUsers(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"users": []interface{}{}})
}

// GetUser handles GET /api/users/:id.
func (h *UserHandler) GetUser(c *gin.Context) {
	idStr := c.Param("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid id"})
		return
	}
	user, err := h.service.GetUser(id)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, user)
}

// CreateUser handles POST /api/users.
func (h *UserHandler) CreateUser(c *gin.Context) {
	var body User
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	user, err := h.service.CreateUser(body.Name, body.Email, body.Role)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, user)
}

// DeleteUser handles DELETE /api/users/:id.
func (h *UserHandler) DeleteUser(c *gin.Context) {
	c.JSON(http.StatusNoContent, nil)
}
