from django.contrib import admin
from django import forms
from .models import TemplateSQL, VariavelTemplate, CredenciaisHubsoft, ClienteConsultado, ConsultaExecucao, ConsultaCliente, CredenciaisBancoDados, MatrixAPIConfig, HSMTemplate, EnvioHSMMatrix, EnvioHSMIndividual

@admin.register(CredenciaisBancoDados)
class CredenciaisBancoDadosAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'tipo_banco', 'host', 'banco', 'ativo', 'data_criacao')
    list_filter = ('tipo_banco', 'ativo')
    search_fields = ('titulo', 'host', 'banco', 'usuario')
    readonly_fields = ('data_criacao', 'data_atualizacao')
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('titulo', 'tipo_banco', 'ativo')
        }),
        ('Conexão', {
            'fields': ('host', 'porta', 'banco')
        }),
        ('Credenciais', {
            'fields': ('usuario', 'senha')
        }),
        ('Datas', {
            'fields': ('data_criacao', 'data_atualizacao'),
            'classes': ('collapse',)
        }),
    )

class VariavelTemplateForm(forms.ModelForm):
    opcoes = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 4, 
            'cols': 50,
            'placeholder': 'Uma opção por linha:\nOpção 1\nOpção 2\nOpção 3'
        }),
        required=False,
        help_text='Para tipo "Lista de Opções": digite uma opção por linha'
    )
    
    class Meta:
        model = VariavelTemplate
        fields = ['nome', 'label', 'tipo', 'obrigatorio', 'valor_padrao', 'opcoes', 'ordem', 'ativo']

class VariavelTemplateInline(admin.TabularInline):
    model = VariavelTemplate
    form = VariavelTemplateForm
    extra = 0
    fields = ['nome', 'label', 'tipo', 'obrigatorio', 'valor_padrao', 'opcoes', 'ordem', 'ativo']
    ordering = ['ordem', 'nome']
    
    def get_queryset(self, request):
        return super().get_queryset(request).order_by('ordem', 'nome')

class TemplateSQLForm(forms.ModelForm):
    variaveis_config = forms.JSONField(
        widget=forms.Textarea(attrs={
            'rows': 6, 
            'cols': 80, 
            'style': 'font-family: monospace; font-size: 12px;'
        }),
        help_text='⚠️ LEGADO: Use a seção "Variáveis" abaixo para uma interface mais amigável. Este campo JSON é mantido para compatibilidade.',
        required=False
    )
    
    class Meta:
        model = TemplateSQL
        fields = '__all__'

@admin.register(TemplateSQL)
class TemplateSQLAdmin(admin.ModelAdmin):
    form = TemplateSQLForm
    inlines = [VariavelTemplateInline]
    list_display = ('titulo', 'ativo', 'get_variaveis_count', 'get_variaveis_detectadas_count', 'data_criacao', 'data_atualizacao')
    list_filter = ('ativo',)
    search_fields = ('titulo', 'descricao')
    readonly_fields = ('data_criacao', 'data_atualizacao', 'get_variaveis_detectadas')
    actions = ['sincronizar_variaveis_acao', 'debug_deteccao_variaveis']
    
    def get_variaveis_count(self, obj):
        """Exibe quantas variáveis estão configuradas"""
        return obj.variaveis.filter(ativo=True).count()
    get_variaveis_count.short_description = 'Variáveis Configuradas'
    
    def get_variaveis_detectadas_count(self, obj):
        """Exibe quantas variáveis foram detectadas no SQL"""
        return len(obj.extrair_variaveis_do_sql())
    get_variaveis_detectadas_count.short_description = 'Variáveis no SQL'
    
    def get_variaveis_detectadas(self, obj):
        """Mostra as variáveis detectadas automaticamente no SQL"""
        variaveis = obj.extrair_variaveis_do_sql()
        if variaveis:
            return ', '.join(variaveis)
        return 'Nenhuma variável detectada'
    get_variaveis_detectadas.short_description = 'Variáveis Detectadas no SQL'
    
    def sincronizar_variaveis_acao(self, request, queryset):
        """Ação para sincronizar variáveis automaticamente"""
        count = 0
        for template in queryset:
            template.sincronizar_variaveis_com_sql()
            count += 1
        
        self.message_user(
            request,
            f'{count} template(s) sincronizado(s) com sucesso. '
            'Variáveis foram criadas/atualizadas conforme encontradas no SQL.'
        )
    sincronizar_variaveis_acao.short_description = 'Sincronizar variáveis com SQL'
    
    def debug_deteccao_variaveis(self, request, queryset):
        """Ação para fazer debug da detecção de variáveis"""
        import json
        from django.contrib import messages
        
        for template in queryset:
            debug_info = template.debug_extrair_variaveis()
            
            # Formata a mensagem de debug
            if 'erro' in debug_info:
                self.message_user(
                    request,
                    f'❌ {template.titulo}: {debug_info["erro"]}',
                    level=messages.ERROR
                )
            else:
                variaveis = ', '.join(debug_info['variaveis_encontradas']) if debug_info['variaveis_encontradas'] else 'Nenhuma'
                self.message_user(
                    request,
                    f'🔍 {template.titulo}: Encontradas {debug_info["total_variaveis_unicas"]} variáveis: {variaveis}',
                    level=messages.INFO
                )
                
                # Debug detalhado no log do Django
                print(f"\n🔍 DEBUG - Template: {template.titulo}")
                print(f"SQL Preview: {debug_info['sql_preview']}")
                print(f"Variáveis encontradas: {debug_info['variaveis_encontradas']}")
                for pattern_name, info in debug_info['patterns_tested'].items():
                    print(f"  {pattern_name}: {info['count']} matches - {info['matches']}")
    
    debug_deteccao_variaveis.short_description = '🔍 Debug: detectar variáveis'
    
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('titulo', 'descricao', 'ativo')
        }),
        ('Consulta SQL', {
            'fields': ('consulta_sql',),
            'description': '💡 Use {{nome_variavel}} para definir variáveis dinâmicas. Exemplo: WHERE data = \'{{data_vencimento}}\'. Após salvar, use a ação "Sincronizar variáveis" para criar automaticamente os campos de variáveis.'
        }),
        ('Detecção Automática', {
            'fields': ('get_variaveis_detectadas',),
            'description': '🔍 Variáveis detectadas automaticamente no SQL acima'
        }),
        ('Sistema Legado (JSON)', {
            'fields': ('variaveis_config',),
            'classes': ('collapse',),
            'description': '⚠️ Campo mantido para compatibilidade. Use a seção "Variáveis" abaixo para uma interface mais amigável.'
        }),
        ('Datas', {
            'fields': ('data_criacao', 'data_atualizacao'),
            'classes': ('collapse',)
        }),
    )

@admin.register(CredenciaisHubsoft)
class CredenciaisHubsoftAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'username', 'ativo', 'data_criacao', 'data_atualizacao')
    list_filter = ('ativo',)
    search_fields = ('titulo', 'username')
    readonly_fields = ('data_criacao', 'data_atualizacao')
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('titulo', 'ativo')
        }),
        ('Credenciais', {
            'fields': ('client_id', 'client_secret', 'username', 'password')
        }),
        ('URLs', {
            'fields': ('url_base', 'url_token')
        }),
        ('Datas', {
            'fields': ('data_criacao', 'data_atualizacao'),
            'classes': ('collapse',)
        }),
    )

@admin.register(ClienteConsultado)
class ClienteConsultadoAdmin(admin.ModelAdmin):
    list_display = ('codigo_cliente', 'nome_razaosocial', 'get_empresa', 'telefone_corrigido', 'data_criacao')
    list_filter = ('credencial_banco', 'data_criacao')
    search_fields = ('codigo_cliente', 'nome_razaosocial', 'telefone_corrigido')
    readonly_fields = ('data_criacao', 'data_atualizacao')
    
    def get_empresa(self, obj):
        """Exibe o nome da empresa/base"""
        if obj.credencial_banco:
            return obj.credencial_banco.titulo
        return "Não definida"
    get_empresa.short_description = 'Empresa/Base'
    get_empresa.admin_order_field = 'credencial_banco__titulo'
    
    fieldsets = (
        ('Informações do Cliente', {
            'fields': ('codigo_cliente', 'nome_razaosocial', 'telefone_corrigido', 'credencial_banco')
        }),
        ('Informações da Fatura', {
            'fields': ('id_fatura', 'vencimento_fatura', 'valor_fatura')
        }),
        ('Informações de Pagamento', {
            'fields': ('pix', 'codigo_barras', 'link_boleto')
        }),
        ('Datas', {
            'fields': ('data_criacao', 'data_atualizacao'),
            'classes': ('collapse',)
        }),
    )

@admin.register(ConsultaExecucao)
class ConsultaExecucaoAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'template_sql', 'status', 'total_registros_sql', 'total_consultados_api', 'total_erros', 'data_inicio', 'data_fim')
    list_filter = ('status', 'template_sql', 'credencial_hubsoft')
    search_fields = ('titulo',)
    readonly_fields = ('data_inicio', 'data_fim', 'total_registros_sql', 'total_consultados_api', 'total_erros', 'get_variaveis_utilizadas', 'get_sql_processado')
    
    def get_variaveis_utilizadas(self, obj):
        """Exibe as variáveis e valores utilizados na execução"""
        if obj.valores_variaveis:
            items = []
            for var, valor in obj.valores_variaveis.items():
                items.append(f"{var}: {valor}")
            return '; '.join(items)
        return 'Nenhuma variável utilizada'
    get_variaveis_utilizadas.short_description = 'Variáveis Utilizadas'
    
    def get_sql_processado(self, obj):
        """Mostra o SQL processado com as variáveis substituídas"""
        if obj.valores_variaveis and obj.template_sql:
            try:
                sql_processado = obj.template_sql.substituir_variaveis(obj.valores_variaveis)
                # Limita o tamanho para exibição
                if len(sql_processado) > 1000:
                    return sql_processado[:1000] + '...\n\n[SQL truncado para exibição]'
                return sql_processado
            except Exception as e:
                return f"Erro ao processar SQL: {str(e)}"
        return 'Sem variáveis para processar'
    get_sql_processado.short_description = 'SQL Processado (com variáveis substituídas)'
    
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('titulo', 'template_sql', 'credencial_hubsoft', 'credencial_banco', 'status')
        }),
        ('Parâmetros da Execução', {
            'fields': ('get_variaveis_utilizadas', 'valores_variaveis', 'get_sql_processado'),
            'description': 'Variáveis e valores utilizados nesta execução'
        }),
        ('Estatísticas', {
            'fields': ('total_registros_sql', 'total_consultados_api', 'total_erros')
        }),
        ('Logs', {
            'fields': ('log_execucao',)
        }),
        ('Datas', {
            'fields': ('data_inicio', 'data_fim')
        }),
    )

@admin.register(ConsultaCliente)
class ConsultaClienteAdmin(admin.ModelAdmin):
    list_display = ('cliente', 'execucao', 'sucesso_api', 'data_consulta')
    list_filter = ('sucesso_api', 'execucao')
    search_fields = ('cliente__nome_razaosocial', 'cliente__codigo_cliente')
    readonly_fields = ('data_consulta',)
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('execucao', 'cliente', 'sucesso_api')
        }),
        ('Dados', {
            'fields': ('dados_originais_sql', 'dados_api_response')
        }),
        ('Erro', {
            'fields': ('erro_api',)
        }),
        ('Datas', {
            'fields': ('data_consulta',)
        }),
    )

@admin.register(MatrixAPIConfig)
class MatrixAPIConfigAdmin(admin.ModelAdmin):
    list_display = ('nome', 'base_url', 'cod_conta', 'ativo', 'data_criacao')
    list_filter = ('ativo',)
    search_fields = ('nome', 'base_url')
    readonly_fields = ('data_criacao', 'data_atualizacao')
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('nome', 'ativo')
        }),
        ('Configurações da API', {
            'fields': ('base_url', 'api_key', 'cod_conta')
        }),
        ('Datas', {
            'fields': ('data_criacao', 'data_atualizacao'),
            'classes': ('collapse',)
        }),
    )

@admin.register(HSMTemplate)
class HSMTemplateAdmin(admin.ModelAdmin):
    list_display = ('nome', 'hsm_id', 'tipo_envio', 'cod_flow', 'ativo', 'data_criacao')
    list_filter = ('tipo_envio', 'ativo')
    search_fields = ('nome', 'descricao')
    readonly_fields = ('data_criacao', 'data_atualizacao')
    
    def get_tipo_envio_display(self, obj):
        return dict(HSMTemplate.TIPO_ENVIO_CHOICES).get(obj.tipo_envio, obj.tipo_envio)
    get_tipo_envio_display.short_description = 'Tipo de Envio'
    
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('nome', 'descricao', 'ativo')
        }),
        ('Configurações HSM', {
            'fields': ('hsm_id', 'cod_flow', 'tipo_envio')
        }),
        ('Variáveis', {
            'fields': ('variaveis_descricao',),
            'description': 'Descrição das variáveis do HSM em formato JSON'
        }),
        ('Datas', {
            'fields': ('data_criacao', 'data_atualizacao'),
            'classes': ('collapse',)
        }),
    )

# =============================================================================
# ADMIN PARA ENVIO HSM MATRIX
# =============================================================================

class EnvioHSMIndividualInline(admin.TabularInline):
    model = EnvioHSMIndividual
    extra = 0
    readonly_fields = ('cliente', 'status', 'data_envio', 'tentativas')
    fields = ('cliente', 'status', 'data_envio', 'tentativas')
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False

@admin.register(EnvioHSMMatrix)
class EnvioHSMMatrixAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'hsm_template', 'matrix_api_config', 'status_envio', 'get_progresso', 'total_clientes', 'data_criacao')
    list_filter = ('status_envio', 'hsm_template', 'matrix_api_config', 'ativo')
    search_fields = ('titulo', 'hsm_template__nome', 'matrix_api_config__nome')
    readonly_fields = ('data_criacao', 'data_inicio_envio', 'data_fim_envio', 'get_progresso', 'get_duracao')
    actions = ['calcular_totais_acao', 'iniciar_envio_acao', 'pausar_envio_acao', 'cancelar_envio_acao']
    inlines = [EnvioHSMIndividualInline]
    
    def get_progresso(self, obj):
        """Exibe o progresso do envio com percentual"""
        if obj.total_clientes == 0:
            return "0% (0/0)"
        percentual = obj.get_progresso_percentual()
        return f"{percentual}% ({obj.total_enviados + obj.total_erros}/{obj.total_clientes})"
    get_progresso.short_description = 'Progresso'
    
    def get_duracao(self, obj):
        """Calcula e exibe a duração do envio"""
        if obj.data_inicio_envio and obj.data_fim_envio:
            duracao = obj.data_fim_envio - obj.data_inicio_envio
            return f"{duracao}"
        elif obj.data_inicio_envio:
            from django.utils import timezone
            duracao = timezone.now() - obj.data_inicio_envio
            return f"{duracao} (em andamento)"
        return "Não iniciado"
    get_duracao.short_description = 'Duração'
    
    def calcular_totais_acao(self, request, queryset):
        """Ação para recalcular totais"""
        count = 0
        for envio in queryset:
            envio.calcular_totais()
            count += 1
        
        self.message_user(
            request,
            f'{count} envio(s) com totais recalculados com sucesso.'
        )
    calcular_totais_acao.short_description = '🔄 Recalcular totais'
    
    def iniciar_envio_acao(self, request, queryset):
        """Ação para iniciar envio"""
        from django.contrib import messages
        count = 0
        for envio in queryset:
            if envio.pode_iniciar():
                envio.atualizar_status('enviando', 'Envio iniciado via admin')
                count += 1
            else:
                self.message_user(
                    request,
                    f'❌ Envio "{envio.titulo}" não pode ser iniciado. Verifique se está ativo e tem dados válidos.',
                    level=messages.WARNING
                )
        
        if count > 0:
            self.message_user(
                request,
                f'{count} envio(s) iniciado(s) com sucesso.'
            )
    iniciar_envio_acao.short_description = '▶️ Iniciar envio'
    
    def pausar_envio_acao(self, request, queryset):
        """Ação para pausar envio"""
        count = 0
        for envio in queryset:
            if envio.status_envio == 'enviando':
                envio.atualizar_status('pausado', 'Envio pausado via admin')
                count += 1
        
        if count > 0:
            self.message_user(
                request,
                f'{count} envio(s) pausado(s) com sucesso.'
            )
    pausar_envio_acao.short_description = '⏸️ Pausar envio'
    
    def cancelar_envio_acao(self, request, queryset):
        """Ação para cancelar envio"""
        count = 0
        for envio in queryset:
            if envio.status_envio in ['pendente', 'enviando', 'pausado']:
                envio.atualizar_status('cancelado', 'Envio cancelado via admin')
                count += 1
        
        if count > 0:
            self.message_user(
                request,
                f'{count} envio(s) cancelado(s) com sucesso.'
            )
    cancelar_envio_acao.short_description = '❌ Cancelar envio'
    
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('titulo', 'ativo')
        }),
        ('Configurações', {
            'fields': ('hsm_template', 'matrix_api_config', 'consulta_execucao')
        }),
        ('Status e Progresso', {
            'fields': ('status_envio', 'get_progresso', 'get_duracao')
        }),
        ('Estatísticas', {
            'fields': ('total_clientes', 'total_enviados', 'total_erros', 'total_pendentes')
        }),
        ('Configurações Avançadas', {
            'fields': ('configuracao_variaveis', 'filtros_adicionais'),
            'classes': ('collapse',),
            'description': 'Configurações avançadas para mapeamento de variáveis e filtros'
        }),
        ('Logs', {
            'fields': ('log_execucao',),
            'classes': ('collapse',)
        }),
        ('Datas', {
            'fields': ('data_criacao', 'data_inicio_envio', 'data_fim_envio'),
            'classes': ('collapse',)
        }),
    )

@admin.register(EnvioHSMIndividual)
class EnvioHSMIndividualAdmin(admin.ModelAdmin):
    list_display = ('cliente', 'envio_matrix', 'status', 'data_envio', 'tentativas')
    list_filter = ('status', 'envio_matrix', 'data_envio')
    search_fields = ('cliente__nome_razaosocial', 'cliente__codigo_cliente', 'envio_matrix__titulo')
    readonly_fields = ('data_envio', 'tentativas', 'get_resposta_api_formatada')
    
    def get_resposta_api_formatada(self, obj):
        """Formata a resposta da API para exibição"""
        if obj.resposta_api:
            import json
            return json.dumps(obj.resposta_api, indent=2, ensure_ascii=False)
        return 'Nenhuma resposta'
    get_resposta_api_formatada.short_description = 'Resposta da API (formatada)'
    
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('envio_matrix', 'cliente', 'status')
        }),
        ('Detalhes do Envio', {
            'fields': ('data_envio', 'tentativas', 'variaveis_utilizadas')
        }),
        ('Resposta da API', {
            'fields': ('get_resposta_api_formatada', 'resposta_api'),
            'classes': ('collapse',)
        }),
        ('Erro', {
            'fields': ('erro_detalhado',),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
