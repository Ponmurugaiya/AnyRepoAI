/**
 * Sample TypeScript module for parser testing.
 * Tests interface, class, enum, method, and NestJS route extraction.
 */

import { Injectable } from '@nestjs/common';
import { Get, Post, Controller, Body, Param } from '@nestjs/common';
import axios from 'axios';

export enum UserRole {
  Admin = 'admin',
  User = 'user',
  Guest = 'guest',
}

export interface UserDto {
  id: number;
  name: string;
  email: string;
  role: UserRole;
}

export abstract class BaseService<T> {
  protected abstract findById(id: number): Promise<T | null>;

  async findOrFail(id: number): Promise<T> {
    const item = await this.findById(id);
    if (!item) throw new Error(`Item ${id} not found`);
    return item;
  }
}

@Injectable()
export class UserService extends BaseService<UserDto> {
  private readonly users: UserDto[] = [];

  protected async findById(id: number): Promise<UserDto | null> {
    return this.users.find(u => u.id === id) ?? null;
  }

  async createUser(dto: Omit<UserDto, 'id'>): Promise<UserDto> {
    const user: UserDto = { id: this.users.length + 1, ...dto };
    this.users.push(user);
    return user;
  }

  private validateEmail(email: string): boolean {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  }
}

@Controller('users')
export class UserController {
  constructor(private readonly userService: UserService) {}

  @Get('/')
  async listUsers(): Promise<UserDto[]> {
    return [];
  }

  @Post('/')
  async createUser(@Body() body: Omit<UserDto, 'id'>): Promise<UserDto> {
    return this.userService.createUser(body);
  }

  @Get('/:id')
  async getUser(@Param('id') id: string): Promise<UserDto> {
    return this.userService.findOrFail(parseInt(id));
  }
}

export const MAX_USERS = 1000;
const defaultRole: UserRole = UserRole.User;
