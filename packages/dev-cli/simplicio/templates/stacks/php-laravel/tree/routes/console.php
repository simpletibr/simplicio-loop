<?php

use Illuminate\Support\Facades\Artisan;

Artisan::command('about:project', function (): void {
    $this->comment('Simplicio Laravel scratch project.');
});
