import { Controller, Get } from "@nestjs/common";

@Controller()
export class AppController {
  @Get("health")
  health(): { ok: boolean } {
    return { ok: true };
  }
}
