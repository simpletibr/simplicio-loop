<?php

use Illuminate\Support\Facades\Route;

Route::get('/health', function (): array {
    return ['status' => 'ok'];
})->name('health');
