#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simplicio 27B: Script de Treinamento com Unsloth (QLoRA 4-bit) & Hugging Face Hub
Desenvolvido para Google Colab (GPU A100 / L4) ou instâncias cloud com GPU NVIDIA.
"""

import os
import sys
import argparse

def parse_args():
    parser = argparse.ArgumentParser(description="Treinamento do Simplicio 27B com Simplicio-Loop (50 Pontos)")
    parser.add_argument("--model_name", type=str, default="Qwen/Qwen3.8-27B", help="Identificador do modelo base no Hugging Face")
    parser.add_argument("--hf_token", type=str, default="YOUR_HF_TOKEN_HERE", help="Hugging Face User Access Token com permissao de escrita")
    parser.add_argument("--hf_repo", type=str, default="wesleysimplicio/Simplicio-27B", help="Repositorio alvo no Hugging Face")
    parser.add_argument("--data_file", type=str, default="./data/simplicio_loop_50pts_train.jsonl", help="Caminho para o dataset de treino em formato JSONL")
    parser.add_argument("--max_seq_length", type=int, default=4096, help="Tamanho maximo de sequencia de contexto")
    parser.add_argument("--lora_r", type=int, default=32, help="Rank do adaptador LoRA")
    parser.add_argument("--lora_alpha", type=int, default=32, help="Alpha do adaptador LoRA")
    parser.add_argument("--batch_size", type=int, default=1, help="Tamanho do batch por dispositivo")
    parser.add_argument("--grad_accum", type=int, default=8, help="Passos de acumulacao de gradiente (efetivo batch 8)")
    parser.add_argument("--max_steps", type=int, default=150, help="Numero maximo de passos de treino")
    parser.add_argument("--learning_rate", type=float, default=2e-4, help="Taxa de aprendizado inicial")
    parser.add_argument("--save_method", type=str, default="lora", choices=["lora", "merged_16bit", "both"], help="Metodo de publicacao no Hub")
    parser.add_argument("--output_dir", type=str, default="./simplicio-27b-checkpoints", help="Diretorio local de saida")
    return parser.parse_args()

def check_gpu():
    try:
        import torch
        if not torch.cuda.is_available():
            print("AVISO: Nenhuma GPU NVIDIA detectada! O treino do modelo de 27B requer GPU A100 (40GB) ou L4 (24GB).")
            print("Se voce estiver no Colab, ative o Runtime GPU: Runtime -> Change runtime type -> A100 GPU.")
        else:
            gpu_name = torch.cuda.get_device_name(0)
            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            print(f"GPU Detectada: {gpu_name} ({vram_gb:.1f} GB VRAM)")
            if vram_gb < 20.0:
                print("ATENCAO: VRAM abaixo de 20GB. Para modelos de 27B, utilize uma A100 ou L4 para evitar OOM.")
    except ImportError:
        print("Torch nao instalado no ambiente atual.")

def main():
    args = parse_args()
    print("=" * 70)
    print("SIMPLICIO 27B: MASTERPLAN DE TREINAMENTO (50 PONTOS SIMPLICIO-LOOP)")
    print(f"Modelo Base: {args.model_name}")
    print(f"Repositorio Alvo: {args.hf_repo}")
    print("=" * 70)

    # 1. Verificar GPU
    check_gpu()

    # 2. Autenticacao no Hugging Face Hub
    token = args.hf_token or os.getenv("HF_TOKEN")
    
    if token:
        print("Autenticando no Hugging Face Hub...")
        try:
            from huggingface_hub import login, HfApi
            login(token=token)
            api = HfApi(token=token)
            user_info = api.whoami()
            print(f"Autenticado com sucesso como: {user_info.get('name', 'Usuario')} (@{user_info.get('username')})")
        except Exception as e:
            print(f"Erro ao autenticar no Hugging Face: {e}")
            print("Verifique se seu token possui permissao 'write' em https://huggingface.co/settings/tokens")
    else:
        print("Nenhum HF_TOKEN informado. O modelo sera treinado e salvo apenas localmente.")
        print("Para enviar ao Hub, forneca --hf_token ou exporte HF_TOKEN=<seu_token>.")

    # 3. Carregar Unsloth e dependencias de treino
    try:
        import torch
        from unsloth import FastLanguageModel
        from trl import SFTTrainer
        from transformers import TrainingArguments
        from datasets import load_dataset
    except ImportError as e:
        print(f"Dependencia faltando: {e}")
        print("Execute no Colab:")
        print("  pip install --no-deps 'xformers<0.0.28' 'trl<0.9.0' peft accelerate bitsandbytes")
        print("  pip install 'unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git'")
        print("  pip install huggingface_hub datasets")
        sys.exit(1)

    # 4. Carregar Modelo Base em 4-bit (QLoRA)
    print(f"Carregando modelo base {args.model_name} em 4-bit...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name = args.model_name,
        max_seq_length = args.max_seq_length,
        dtype = None,
        load_in_4bit = True,
    )

    # 5. Configurar Adaptadores LoRA
    print(f"Configurando LoRA (r={args.lora_r}, alpha={args.lora_alpha})...")
    model = FastLanguageModel.get_peft_model(
        model,
        r = args.lora_r,
        target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                          "gate_proj", "up_proj", "down_proj"],
        lora_alpha = args.lora_alpha,
        lora_dropout = 0,
        bias = "none",
        use_gradient_checkpointing = "unsloth",
        random_state = 3407,
    )

    # 6. Carregar e Formatar Dataset do Simplicio-Loop
    if not os.path.exists(args.data_file):
        print(f"Arquivo de dados {args.data_file} nao encontrado! Gerando synthetic dataset...")
        gen_script = os.path.join(os.path.dirname(__file__), "generate_dataset.py")
        if os.path.exists(gen_script):
            os.system(f"python3 {gen_script}")
        else:
            raise FileNotFoundError(f"Arquivo de treino {args.data_file} nao encontrado.")

    print(f"Carregando dataset: {args.data_file}...")
    dataset = load_dataset("json", data_files={"train": args.data_file}, split="train")

    system_prompt = (
        "Voce e o Simplicio 27B, treinado para executar tarefas de desenvolvimento "
        "seguindo rigorosamente os 50 pontos do Simplicio-Loop: Orientacao, Planejamento, "
        "Edicao Cirurgica por Diff, Validacao e Entrega Verificada sem alucinacao."
    )

    def formatting_prompts_func(examples):
        instructions = examples["instruction"]
        inputs       = examples["context"]
        outputs      = examples["simplicio_trajectory"]
        texts = []
        for instruction, input_ctx, output in zip(instructions, inputs, outputs):
            text = (
                f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
                f"<|im_start|>user\nContexto do Repo: {input_ctx}\nTarefa: {instruction}<|im_end|>\n"
                f"<|im_start|>assistant\n{output}<|im_end|>"
            )
            texts.append(text)
        return { "text": texts }

    formatted_dataset = dataset.map(formatting_prompts_func, batched=True)
    print(f"Dataset preparado: {len(formatted_dataset)} exemplos formatados em ChatML.")

    # 7. Configurar Trainer (SFTTrainer)
    trainer = SFTTrainer(
        model = model,
        tokenizer = tokenizer,
        train_dataset = formatted_dataset,
        dataset_text_field = "text",
        max_seq_length = args.max_seq_length,
        dataset_num_proc = 2,
        packing = False,
        args = TrainingArguments(
            per_device_train_batch_size = args.batch_size,
            gradient_accumulation_steps = args.grad_accum,
            warmup_steps = 10,
            max_steps = args.max_steps,
            learning_rate = args.learning_rate,
            fp16 = not torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False,
            bf16 = torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False,
            logging_steps = 5,
            optim = "adamw_8bit",
            weight_decay = 0.01,
            lr_scheduler_type = "cosine",
            seed = 3407,
            output_dir = args.output_dir,
            report_to = "none",
        ),
    )

    # 8. Executar Treinamento
    print("Iniciando Fine-Tuning do Simplicio 27B...")
    trainer_stats = trainer.train()
    print("Treinamento concluido com sucesso!")
    print(f"Perda final: {trainer_stats.training_loss:.4f}")

    # 9. Teste de Inferencia Local
    print("Executando teste de inferencia do Simplicio-Loop...")
    FastLanguageModel.for_inference(model)
    test_input = tokenizer(
        [
            f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
            f"<|im_start|>user\nContexto: API FastAPI com erro de chave duplicada no schema.\nTarefa: Aplicar correcao cirurgica seguindo os 50 pontos.<|im_end|>\n"
            f"<|im_start|>assistant\n"
        ],
        return_tensors = "pt"
    ).to("cuda" if torch.cuda.is_available() else "cpu")

    outputs = model.generate(**test_input, max_new_tokens=256, use_cache=True)
    decoded = tokenizer.decode(outputs[0], skip_special_tokens=False)
    print("--- Saida do Simplicio 27B (Preview) ---")
    print(decoded[:500] + "...")

    # 10. Publicacao no Hugging Face Hub
    if token and args.hf_repo:
        print(f"Publicando modelo no Hugging Face: {args.hf_repo}...")
        try:
            if args.save_method in ["lora", "both"]:
                print("Enviando adaptadores LoRA (~500MB)...")
                model.push_to_hub_merged(
                    args.hf_repo,
                    tokenizer,
                    save_method = "lora",
                    token = token
                )
                print(f"LoRA publicado em https://huggingface.co/{args.hf_repo}")

            if args.save_method in ["merged_16bit", "both"]:
                merged_repo = f"{args.hf_repo}-16bit"
                print(f"Mesclando e enviando modelo 16-bit completo para {merged_repo}...")
                model.push_to_hub_merged(
                    merged_repo,
                    tokenizer,
                    save_method = "merged_16bit",
                    token = token
                )
                print(f"Modelo 16-bit publicado em https://huggingface.co/{merged_repo}")

        except Exception as e:
            print(f"Erro ao publicar no Hub: {e}")
            print(f"Salvando copia local em {args.output_dir}...")
            model.save_pretrained(args.output_dir)
            tokenizer.save_pretrained(args.output_dir)
    else:
        print(f"Salvando adaptadores localmente em: {args.output_dir}...")
        model.save_pretrained(args.output_dir)
        tokenizer.save_pretrained(args.output_dir)
        print("Concluido!")

if __name__ == "__main__":
    main()
