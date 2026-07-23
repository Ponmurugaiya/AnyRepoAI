/**
 * Sample JavaScript module for parser tests.
 * Tests class, function, arrow function, import, require, and Express route extraction.
 */

'use strict';

const express = require('express');
import axios from 'axios';
import { readFileSync, writeFileSync } from 'fs';

const MAX_CONNECTIONS = 10;
let connectionCount = 0;

/**
 * Base class for all handlers.
 */
class BaseHandler {
  constructor(name) {
    this.name = name;
    this._cache = new Map();
  }

  /**
   * Handle an incoming request.
   * @param {object} req - Request object.
   * @param {object} res - Response object.
   */
  handle(req, res) {
    res.json({ handler: this.name });
  }

  _getCached(key) {
    return this._cache.get(key);
  }
}

/**
 * User handler extending BaseHandler.
 */
class UserHandler extends BaseHandler {
  constructor() {
    super('UserHandler');
    this.users = [];
  }

  createUser(name, email) {
    const user = { id: this.users.length + 1, name, email };
    this.users.push(user);
    return user;
  }

  async getUser(id) {
    return this.users.find(u => u.id === id) ?? null;
  }
}

// Arrow function assigned to const
const validateEmail = (email) => {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
};

// Regular async function
async function fetchUserData(userId, options = {}) {
  const { timeout = 5000 } = options;
  const response = await axios.get(`/api/users/${userId}`, { timeout });
  return response.data;
}

// Express router setup
const router = express.Router();
const app = express();

app.get('/health', (req, res) => {
  res.json({ status: 'ok' });
});

router.get('/users', async (req, res) => {
  res.json({ users: [] });
});

router.post('/users', async (req, res) => {
  const handler = new UserHandler();
  const user = handler.createUser(req.body.name, req.body.email);
  res.status(201).json(user);
});

router.get('/users/:id', async (req, res) => {
  const handler = new UserHandler();
  const user = await handler.getUser(parseInt(req.params.id));
  if (!user) return res.status(404).json({ error: 'Not found' });
  res.json(user);
});

router.delete('/users/:id', (req, res) => {
  res.status(204).send();
});

module.exports = { UserHandler, validateEmail, fetchUserData, router };
