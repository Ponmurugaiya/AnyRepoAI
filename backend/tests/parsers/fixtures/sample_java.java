package com.example.api;

import java.util.List;
import java.util.Optional;
import org.springframework.web.bind.annotation.*;
import org.springframework.stereotype.Service;

/**
 * Sample Java source used by parser tests.
 * Exercises class, interface, enum, method, and Spring Boot route extraction.
 */
public class SampleJava {

    /** User roles enumeration. */
    public enum Role {
        ADMIN, USER, GUEST
    }

    /** Repository interface for user data access. */
    public interface UserRepository {
        Optional<User> findById(Long id);
        List<User> findAll();
        User save(User user);
        void deleteById(Long id);
    }

    /** User domain model. */
    public static class User {
        private Long id;
        private String name;
        private String email;
        private Role role;

        public User(Long id, String name, String email, Role role) {
            this.id = id;
            this.name = name;
            this.email = email;
            this.role = role;
        }

        public Long getId() { return id; }
        public String getName() { return name; }
        public String getEmail() { return email; }
        public Role getRole() { return role; }

        private boolean isValid() {
            return name != null && !name.isEmpty() && email != null && email.contains("@");
        }
    }

    /** Service layer for user operations. */
    @Service
    public static class UserService {
        private final UserRepository repository;

        public UserService(UserRepository repository) {
            this.repository = repository;
        }

        public User getUser(Long id) {
            return repository.findById(id)
                .orElseThrow(() -> new RuntimeException("User not found: " + id));
        }

        public List<User> getAllUsers() {
            return repository.findAll();
        }

        public User createUser(String name, String email, Role role) {
            User user = new User(null, name, email, role);
            return repository.save(user);
        }

        protected void deleteUser(Long id) {
            repository.deleteById(id);
        }
    }

    /** REST controller exposing user API. */
    @RestController
    @RequestMapping("/api/users")
    public static class UserController {
        private final UserService userService;

        public UserController(UserService userService) {
            this.userService = userService;
        }

        @GetMapping
        public List<User> listUsers() {
            return userService.getAllUsers();
        }

        @GetMapping("/{id}")
        public User getUser(@PathVariable Long id) {
            return userService.getUser(id);
        }

        @PostMapping
        public User createUser(@RequestBody User body) {
            return userService.createUser(body.getName(), body.getEmail(), body.getRole());
        }

        @DeleteMapping("/{id}")
        public void deleteUser(@PathVariable Long id) {
            userService.deleteUser(id);
        }
    }
}
