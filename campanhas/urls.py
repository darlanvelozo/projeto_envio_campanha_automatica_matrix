from django.urls import path
from . import views

urlpatterns = [
    path('processar-consulta/', views.pagina_processar_consulta, name='pagina_processar_consulta'),
    path('template/<int:template_id>/variaveis/', views.obter_variaveis_template, name='obter_variaveis_template'),
    path('iniciar-processamento/', views.iniciar_processamento, name='iniciar_processamento'),
    path('', views.listar_execucoes, name='listar_execucoes'),
    path('execucao/<int:execucao_id>/', views.detalhe_execucao, name='detalhe_execucao'),
    path('execucao/<int:execucao_id>/status/', views.status_execucao_ajax, name='status_execucao_ajax'),
    path('execucao/<int:execucao_id>/exportar/', views.exportar_resultados_csv, name='exportar_resultados_csv'),
    path('execucao/<int:execucao_id>/exportar-erros/', views.exportar_erros_csv, name='exportar_erros_csv'),
    path('execucao/<int:execucao_id>/cancelar/', views.cancelar_processamento, name='cancelar_processamento'),
    path('execucao/<int:execucao_id>/reiniciar/', views.reiniciar_processamento, name='reiniciar_processamento'),
    path('cliente/<int:cliente_id>/detalhes/', views.detalhes_cliente, name='detalhes_cliente'),
    
    # URLs para envio HSM
    path('execucao/<int:execucao_id>/configurar-hsm/', views.configurar_envio_hsm, name='configurar_envio_hsm'),
    path('execucao/<int:execucao_id>/enviar-hsm-atual/', views.enviar_hsm_configuracao_atual, name='enviar_hsm_configuracao_atual'),
    path('hsm-template/<int:template_id>/variaveis/', views.obter_variaveis_hsm_template, name='obter_variaveis_hsm_template'),
    path('iniciar-envio-hsm/', views.iniciar_envio_hsm, name='iniciar_envio_hsm'),
    path('envios-hsm/', views.listar_envios_hsm, name='listar_envios_hsm'),
    path('envio-hsm/<int:envio_id>/', views.detalhe_envio_hsm, name='detalhe_envio_hsm'),
    path('envio-hsm/<int:envio_id>/status/', views.status_envio_hsm_ajax, name='status_envio_hsm_ajax'),
    path('envio-hsm/<int:envio_id>/cancelar/', views.cancelar_envio_hsm, name='cancelar_envio_hsm'),
] 