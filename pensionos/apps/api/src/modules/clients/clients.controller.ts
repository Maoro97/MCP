import {
  Body,
  Controller,
  Get,
  Param,
  ParseUUIDPipe,
  Post,
  Query,
  UseGuards,
} from '@nestjs/common';

import { AuthGuard } from '../../common/auth.guard';
import { CurrentUser, type Principal } from '../../common/principal';
import {
  ClientsService,
  CreateClientSchema,
  type ClientSummary,
} from './clients.service';
import { PortfolioService, type PortfolioView } from '../portfolio/portfolio.service';

@Controller('v1/clients')
@UseGuards(AuthGuard)
export class ClientsController {
  constructor(
    private readonly clients: ClientsService,
    private readonly portfolio: PortfolioService,
  ) {}

  @Get()
  list(
    @CurrentUser() principal: Principal,
    @Query('q') q?: string,
  ): Promise<ClientSummary[]> {
    return this.clients.list(principal, q?.trim() || undefined);
  }

  @Post()
  create(@CurrentUser() principal: Principal, @Body() body: unknown) {
    return this.clients.create(principal, CreateClientSchema.parse(body));
  }

  @Get(':id/portfolio')
  getPortfolio(
    @CurrentUser() principal: Principal,
    @Param('id', ParseUUIDPipe) id: string,
  ): Promise<PortfolioView> {
    return this.portfolio.getPortfolio(principal, id);
  }
}
